import { useState, useEffect } from 'react'
import GraphViewer from './components/GraphViewer'
import ChatPanel from './components/ChatPanel'
import NodePanel from './components/NodePanel'

const API_BASE = '/api'

function App() {
  const [graphData, setGraphData] = useState(null)
  const [entityTypes, setEntityTypes] = useState({})
  const [selectedNode, setSelectedNode] = useState(null)
  const [highlightedNodes, setHighlightedNodes] = useState(new Set())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Clustering state
  const [clusterMode, setClusterMode] = useState(false)
  const [clusterData, setClusterData] = useState(null)
  const [clusterLoading, setClusterLoading] = useState(false)

  // Semantic search state
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState(null)  // null = no search, [] = no results

  useEffect(() => {
    loadGraph()
  }, [])

  async function loadGraph() {
    try {
      setLoading(true)
      const graphRes = await fetch(`${API_BASE}/graph?max_nodes=200&max_edges=2000`)
      if (!graphRes.ok) throw new Error('Failed to load graph')
      const data = await graphRes.json()
      setGraphData({ nodes: data.nodes, links: data.links })
      if (data.entity_types) {
        setEntityTypes(data.entity_types)
      }
    } catch (err) {
      console.error('Failed to load graph:', err)
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function toggleClusterMode() {
    if (clusterMode) {
      setClusterMode(false)
      return
    }
    // Load cluster data on first enable
    if (!clusterData) {
      setClusterLoading(true)
      try {
        const res = await fetch(`${API_BASE}/graph/clusters`)
        if (!res.ok) throw new Error('Failed to load clusters')
        const data = await res.json()
        // data.clusters is array of {id, nodes: [...nodeIds]}
        const map = {}
        if (data.clusters) {
          data.clusters.forEach(cluster => {
            cluster.nodes.forEach(nodeId => {
              map[nodeId] = cluster.id
            })
          })
        }
        setClusterData(map)
      } catch (err) {
        console.error('Cluster load failed:', err)
      } finally {
        setClusterLoading(false)
      }
    }
    setClusterMode(true)
  }

  async function handleSearch(q) {
    const query = q.trim()
    setSearchQuery(q)
    if (!query) {
      setSearchResults(null)
      setHighlightedNodes(new Set())
      return
    }
    try {
      const res = await fetch(`${API_BASE}/search?q=${encodeURIComponent(query)}&limit=20`)
      const data = await res.json()
      setSearchResults(data.results)
      setHighlightedNodes(new Set(data.results.map(r => r.id)))
    } catch (e) {
      console.error('Search error:', e)
    }
  }

  function handleSearchSubmit(e) {
    e.preventDefault()
    handleSearch(searchQuery)
  }

  function handleNodeClick(node) {
    setSelectedNode(node)
  }

  function handleExpandNode(nodeId) {
    fetch(`${API_BASE}/graph/node/${encodeURIComponent(nodeId)}?depth=1`)
      .then(res => res.json())
      .then(data => {
        if (!data.nodes || data.nodes.length === 0) return
        setGraphData(prev => {
          const existingIds = new Set(prev.nodes.map(n => n.id))
          const newNodes = data.nodes.filter(n => !existingIds.has(n.id))
          const existingEdges = new Set(
            prev.links.map(l => `${l.source?.id || l.source}-${l.target?.id || l.target}`)
          )
          const newLinks = data.links.filter(l => {
            const key = `${l.source?.id || l.source}-${l.target?.id || l.target}`
            return !existingEdges.has(key)
          })
          return {
            nodes: [...prev.nodes, ...newNodes],
            links: [...prev.links, ...newLinks],
          }
        })
      })
      .catch(err => console.error('Failed to expand node:', err))
  }

  if (loading) {
    return (
      <div className="loading-overlay">
        <div className="loading-spinner" />
        <div className="loading-text">Loading graph data...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="loading-overlay">
        <div style={{ color: 'var(--accent-rose)', fontSize: 18, fontWeight: 600 }}>
          Failed to connect
        </div>
        <div className="loading-text">{error}</div>
        <button
          onClick={loadGraph}
          style={{
            padding: '10px 24px',
            background: 'var(--accent-blue)',
            border: 'none',
            borderRadius: 8,
            color: 'white',
            cursor: 'pointer',
            fontSize: 14,
          }}
        >
          Retry
        </button>
      </div>
    )
  }

  const totalNodes = graphData?.nodes?.length || 0
  const totalEdges = graphData?.links?.length || 0

  return (
    <div className="app">
      <header className="header">
        <div className="header__logo">
          <div className="header__icon">D</div>
          <div>
            <div className="header__title">Dodgeai</div>
            <div className="header__subtitle">Graph Query System</div>
          </div>
        </div>
        <div className="header__stats">
          <div className="header__stat">
            Nodes <span className="header__stat-value">{totalNodes}</span>
          </div>
          <div className="header__stat">
            Edges <span className="header__stat-value">{totalEdges}</span>
          </div>
          <div className="header__stat">
            Types <span className="header__stat-value">{Object.keys(entityTypes).length}</span>
          </div>

          {/* Semantic search bar */}
          <form className="search-bar" onSubmit={handleSearchSubmit}>
            <span className="search-bar__icon">🔍</span>
            <input
              className="search-bar__input"
              type="text"
              placeholder="Search entities..."
              value={searchQuery}
              onChange={e => handleSearch(e.target.value)}
              onKeyDown={e => e.key === 'Escape' && handleSearch('')}
            />
            {searchResults !== null && (
              <span className="search-bar__badge">
                {searchResults.length}
              </span>
            )}
          </form>

          {/* Cluster mode toggle */}
          <button
            className={`cluster-toggle ${clusterMode ? 'cluster-toggle--active' : ''}`}
            onClick={toggleClusterMode}
            disabled={clusterLoading}
            title="Toggle graph clustering view"
          >
            {clusterLoading ? '⌛' : clusterMode ? '🔵 Clusters ON' : '⬡ Clusters'}
          </button>
          {clusterMode && highlightedNodes.size > 0 && (
            <button
              className="cluster-toggle"
              onClick={() => setHighlightedNodes(new Set())}
              title="Clear chat highlights"
            >
              ✕ Highlights
            </button>
          )}
        </div>
      </header>

      <div className="main-content">
        <div className="graph-panel">
          {graphData && (
            <GraphViewer
              graphData={graphData}
              entityTypes={entityTypes}
              highlightedNodes={highlightedNodes}
              clusterMode={clusterMode}
              clusterData={clusterData}
              onNodeClick={handleNodeClick}
              onExpandNode={handleExpandNode}
            />
          )}
          {selectedNode && (
            <NodePanel
              node={selectedNode}
              onClose={() => setSelectedNode(null)}
              onExpand={() => handleExpandNode(selectedNode.id)}
            />
          )}
        </div>

        <ChatPanel
          onHighlightNodes={setHighlightedNodes}
        />
      </div>
    </div>
  )
}

export default App
