export default function NodePanel({ node, onClose, onExpand }) {
  if (!node) return null

  // Collect all node attributes for display
  const fields = Object.entries(node).filter(
    ([key]) => !['x', 'y', 'vx', 'vy', 'fx', 'fy', 'index', '__indexColor'].includes(key)
  )

  return (
    <div className="node-panel">
      <div className="node-panel__header">
        <div>
          <div className="node-panel__type">{node.type || 'Entity'}</div>
          <div style={{ fontSize: 14, fontWeight: 600, marginTop: 4 }}>
            {node.label || node.id}
          </div>
        </div>
        <button className="node-panel__close" onClick={onClose} title="Close">
          ✕
        </button>
      </div>

      <div className="node-panel__body">
        {fields.map(([key, value]) => (
          <div key={key} className="node-panel__field">
            <div className="node-panel__field-label">{key}</div>
            <div className="node-panel__field-value">
              {value === null || value === undefined
                ? '—'
                : typeof value === 'object'
                ? JSON.stringify(value, null, 2)
                : String(value)}
            </div>
          </div>
        ))}

        <button
          onClick={onExpand}
          style={{
            marginTop: 16,
            width: '100%',
            padding: '10px',
            background: 'linear-gradient(135deg, var(--accent-blue), var(--accent-indigo))',
            color: 'white',
            border: 'none',
            borderRadius: 'var(--radius-md)',
            cursor: 'pointer',
            fontSize: 12,
            fontWeight: 600,
            transition: 'all var(--transition-fast)',
          }}
        >
          Expand Neighbors
        </button>
      </div>
    </div>
  )
}
