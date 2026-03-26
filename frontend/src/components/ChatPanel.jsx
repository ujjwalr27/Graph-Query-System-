import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const API_BASE = '/api'

const SUGGESTIONS = [
  'Which products are associated with the highest number of billing documents?',
  'Trace the full flow of a specific billing document',
  'Identify sales orders that have broken or incomplete flows',
  'Show me the top 5 customers by total order value',
  'Which deliveries have not been billed yet?',
]

export default function ChatPanel({ onHighlightNodes }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [sessionId, setSessionId] = useState(null)
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  // Extract all scalar values from SQL results as potential node IDs
  function extractNodeIds(results) {
    if (!Array.isArray(results) || results.length === 0) return new Set()
    const ids = new Set()
    results.forEach(row => {
      Object.values(row).forEach(val => {
        if (val !== null && val !== undefined && val !== '') {
          ids.add(String(val))
        }
      })
    })
    return ids
  }

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function sendMessage(text) {
    if (!text.trim() || isLoading) return

    const userMessage = { role: 'user', content: text }
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setIsLoading(true)

    try {
      const response = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          session_id: sessionId,
          stream: true,
        }),
      })

      if (!response.ok) {
        throw new Error('Chat request failed')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()

      let assistantContent = ''
      let sqlInfo = null
      let buffer = ''
      let sqlResults = null  // track results for node highlighting
      let warningText = null  // fan-out or other warnings

      // Create placeholder assistant message
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: '', sql: null, loading: true },
      ])

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const jsonStr = line.slice(6).trim()
          if (!jsonStr) continue

          try {
            const data = JSON.parse(jsonStr)

            switch (data.type) {
              case 'session':
                setSessionId(data.session_id)
                break

              case 'results_count':
                // Store results count — actual highlighting happens on done
                break

              case 'warning':
                warningText = data.content
                setMessages(prev => {
                  const updated = [...prev]
                  const last = updated[updated.length - 1]
                  if (last?.role === 'assistant') last.warning = warningText
                  return [...updated]
                })
                break

              case 'results':
                sqlResults = data.rows || []
                break

              case 'sql':
                sqlInfo = { sql: data.sql, explanation: data.explanation }
                setMessages(prev => {
                  const updated = [...prev]
                  const last = updated[updated.length - 1]
                  if (last?.role === 'assistant') {
                    last.sql = sqlInfo
                  }
                  return updated
                })
                break

              case 'chunk':
                assistantContent += data.content
                setMessages(prev => {
                  const updated = [...prev]
                  const last = updated[updated.length - 1]
                  if (last?.role === 'assistant') {
                    last.content = assistantContent
                    last.loading = false
                  }
                  return [...updated]
                })
                break

              case 'guardrail':
              case 'answer':
                assistantContent = data.content
                setMessages(prev => {
                  const updated = [...prev]
                  const last = updated[updated.length - 1]
                  if (last?.role === 'assistant') {
                    last.content = assistantContent
                    last.loading = false
                    last.isGuardrail = data.type === 'guardrail'
                  }
                  return [...updated]
                })
                break

              case 'error':
                setMessages(prev => {
                  const updated = [...prev]
                  const last = updated[updated.length - 1]
                  if (last?.role === 'assistant') {
                    last.content = `⚠️ ${data.content}`
                    last.loading = false
                    last.isError = true
                  }
                  return [...updated]
                })
                break

              case 'done':
                // Highlight nodes from the last SQL results
                if (sqlResults && onHighlightNodes) {
                  onHighlightNodes(extractNodeIds(sqlResults))
                }
                break
            }
          } catch (e) {
            // Skip malformed JSON
          }
        }
      }
    } catch (err) {
      console.error('Chat error:', err)
      setMessages(prev => {
        const updated = [...prev]
        const last = updated[updated.length - 1]
        if (last?.role === 'assistant') {
          last.content = '⚠️ Failed to get response. Is the backend running?'
          last.loading = false
          last.isError = true
        } else {
          updated.push({
            role: 'assistant',
            content: '⚠️ Failed to get response. Is the backend running?',
            isError: true,
          })
        }
        return [...updated]
      })
    } finally {
      setIsLoading(false)
      inputRef.current?.focus()
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage(input)
    }
  }

  function handleClear() {
    setMessages([])
    if (sessionId) {
      fetch(`${API_BASE}/chat/session/${sessionId}`, { method: 'DELETE' }).catch(() => {})
    }
    setSessionId(null)
    onHighlightNodes?.(new Set())
  }

  const hasMessages = messages.length > 0

  return (
    <div className="chat-panel">
      <div className="chat-panel__header">
        <div className="chat-panel__title">
          <div className="chat-panel__title-dot" />
          AI Assistant
        </div>
        {hasMessages && (
          <button className="chat-panel__clear" onClick={handleClear}>
            Clear
          </button>
        )}
      </div>

      <div className="chat-panel__messages">
        {!hasMessages ? (
          <div className="chat-welcome">
            <div className="chat-welcome__icon">💬</div>
            <div className="chat-welcome__title">Ask about your data</div>
            <div className="chat-welcome__description">
              Ask questions in natural language and I'll query the dataset for you.
              Try one of these suggestions:
            </div>
            <div className="chat-welcome__suggestions">
              {SUGGESTIONS.map((s, i) => (
                <button
                  key={i}
                  className="chat-welcome__suggestion"
                  onClick={() => sendMessage(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg, i) => (
            <div key={i} className={`message message--${msg.role}`}>
              <div className="message__bubble">
                {msg.loading ? (
                  <div className="typing-indicator">
                    <span /><span /><span />
                  </div>
                ) : msg.role === 'assistant' ? (
                  <div className="message__markdown">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                  </div>
                ) : (
                  msg.content
                )}
              </div>
              {msg.warning && (
                <div className="message__warning">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.warning}</ReactMarkdown>
                </div>
              )}
              {msg.sql && (
                <div className="message__sql">
                  <div className="message__sql-label">Generated SQL</div>
                  {msg.sql.sql}
                </div>
              )}
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="chat-panel__input-area">
        <div className="chat-panel__input-wrapper">
          <textarea
            ref={inputRef}
            className="chat-panel__input"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question about the data..."
            rows={1}
            disabled={isLoading}
          />
          <button
            className="chat-panel__send"
            onClick={() => sendMessage(input)}
            disabled={isLoading || !input.trim()}
            title="Send message"
          >
            ➤
          </button>
        </div>
      </div>
    </div>
  )
}
