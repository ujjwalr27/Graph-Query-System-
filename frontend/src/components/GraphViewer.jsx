import { useRef, useEffect, useCallback, useMemo } from 'react'
import ForceGraph2D from 'react-force-graph-2d'

// Color map for entity types
const TYPE_COLORS = {
  // Core flow
  orders: '#3b82f6',
  order: '#3b82f6',
  purchase_order: '#3b82f6',
  sales_order: '#3b82f6',
  deliveries: '#10b981',
  delivery: '#10b981',
  invoices: '#f59e0b',
  invoice: '#f59e0b',
  billing: '#f59e0b',
  billing_document: '#f59e0b',
  payments: '#8b5cf6',
  payment: '#8b5cf6',
  journal_entry: '#8b5cf6',
  // Supporting
  customers: '#f43f5e',
  customer: '#f43f5e',
  products: '#06b6d4',
  product: '#06b6d4',
  material: '#06b6d4',
  addresses: '#64748b',
  address: '#64748b',
  plant: '#64748b',
}

// Distinct colors for up to 12 clusters
const CLUSTER_COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#f43f5e', '#06b6d4',
  '#6366f1', '#ec4899', '#14b8a6', '#f97316', '#84cc16', '#a855f7',
]

const DEFAULT_COLOR = '#6366f1'

function getNodeColor(type) {
  if (!type) return DEFAULT_COLOR
  const lower = type.toLowerCase()
  return TYPE_COLORS[lower] || DEFAULT_COLOR
}

function getClusterColor(clusterId) {
  if (clusterId === undefined || clusterId === null) return DEFAULT_COLOR
  return CLUSTER_COLORS[clusterId % CLUSTER_COLORS.length]
}

export default function GraphViewer({
  graphData,
  entityTypes,
  highlightedNodes,
  clusterMode,
  clusterData,
  onNodeClick,
  onExpandNode,
}) {
  const graphRef = useRef()

  // Use refs for values that change without needing to restart the force simulation
  const clusterModeRef = useRef(clusterMode)
  const clusterDataRef = useRef(clusterData)
  const highlightedRef = useRef(highlightedNodes)
  useEffect(() => { clusterModeRef.current = clusterMode }, [clusterMode])
  useEffect(() => { clusterDataRef.current = clusterData }, [clusterData])
  useEffect(() => { highlightedRef.current = highlightedNodes }, [highlightedNodes])

  useEffect(() => {
    if (graphRef.current) {
      setTimeout(() => {
        graphRef.current.zoomToFit(400, 40)
      }, 500)
    }
  }, [graphData])

  // Force re-paint when cluster/highlight state changes (without restarting simulation)
  useEffect(() => {
    if (graphRef.current) {
      graphRef.current.refresh()
    }
  }, [clusterMode, clusterData, highlightedNodes])

  const handleNodeClick = useCallback(
    (node) => {
      if (onNodeClick) onNodeClick(node)
    },
    [onNodeClick]
  )

  const handleNodeDoubleClick = useCallback(
    (node) => {
      if (onExpandNode) onExpandNode(node.id)
    },
    [onExpandNode]
  )

  // Stable callback — reads from refs so it never changes identity
  const nodeCanvasObject = useCallback(
    (node, ctx, globalScale) => {
      const isHighlighted = highlightedRef.current?.has(node.id)
      const baseR = isHighlighted ? 3.5 : 2.5
      const r = Math.max(baseR / Math.sqrt(globalScale), 1.5)

      // Color: cluster mode uses cluster color, otherwise entity type color
      const color = clusterModeRef.current
        ? getClusterColor(clusterDataRef.current?.[node.id])
        : getNodeColor(node.type)

      // Outer glow for highlighted nodes
      if (isHighlighted) {
        ctx.beginPath()
        ctx.arc(node.x, node.y, r + 3, 0, 2 * Math.PI)
        ctx.fillStyle = color + '28'
        ctx.fill()
      }

      // Node circle
      ctx.beginPath()
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI)
      ctx.fillStyle = color
      ctx.fill()

      // Border
      ctx.strokeStyle = isHighlighted ? '#fff' : color + '60'
      ctx.lineWidth = isHighlighted ? 1 : 0.4
      ctx.stroke()

      // Label
      if (globalScale > 0.5) {
        const label = node.label || node.id
        const fontSize = Math.max(8 / globalScale, 3)
        ctx.font = `${fontSize}px Inter, sans-serif`
        ctx.textAlign = 'center'
        ctx.textBaseline = 'top'
        ctx.fillStyle = isHighlighted ? '#e2e8f0' : '#64748b'
        ctx.fillText(String(label).substring(0, 20), node.x, node.y + r + 1.5)
      }
    },
    [] // empty deps — reads from refs, so identity is stable
  )

  const linkCanvasObject = useCallback((link, ctx, globalScale) => {
    const start = link.source
    const end = link.target
    if (!start || !end || typeof start.x === 'undefined') return

    // Draw the edge line
    ctx.beginPath()
    ctx.moveTo(start.x, start.y)
    ctx.lineTo(end.x, end.y)
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.08)'
    ctx.lineWidth = 0.5
    ctx.stroke()

    // Draw edge label at midpoint when zoomed in enough
    if (globalScale > 1.2 && link.relation) {
      const midX = (start.x + end.x) / 2
      const midY = (start.y + end.y) / 2
      const label = link.relation
      const fontSize = Math.max(5 / globalScale, 2)

      ctx.font = `${fontSize}px Inter, sans-serif`
      const textWidth = ctx.measureText(label).width
      const padding = fontSize * 0.4

      // Pill background
      ctx.fillStyle = 'rgba(15, 23, 42, 0.85)'
      ctx.beginPath()
      ctx.roundRect(
        midX - textWidth / 2 - padding,
        midY - fontSize / 2 - padding,
        textWidth + padding * 2,
        fontSize + padding * 2,
        2
      )
      ctx.fill()

      // Label text
      ctx.fillStyle = 'rgba(148, 163, 184, 0.9)'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(label, midX, midY)
    }
  }, [])

  // Legend: cluster mode shows cluster IDs, otherwise entity types
  const legendItems = useMemo(() => {
    if (clusterMode && clusterData) {
      const clusterIds = [...new Set(Object.values(clusterData))].sort((a, b) => a - b)
      return clusterIds.map(id => ({
        label: `Cluster ${id}`,
        color: getClusterColor(id),
      }))
    }
    if (!graphData?.nodes) return []
    const types = new Set(graphData.nodes.map(n => n.type))
    return Array.from(types).sort().map(type => ({
      label: type,
      color: getNodeColor(type),
      count: entityTypes[type],
    }))
  }, [graphData, entityTypes, clusterMode, clusterData])

  return (
    <>
      <div className="graph-panel__canvas">
        <ForceGraph2D
          ref={graphRef}
          graphData={graphData || { nodes: [], links: [] }}
          nodeCanvasObject={nodeCanvasObject}
          linkCanvasObject={linkCanvasObject}
          onNodeClick={handleNodeClick}
          onNodeRightClick={handleNodeDoubleClick}
          nodeId="id"
          linkSource="source"
          linkTarget="target"
          backgroundColor="#0a0e17"
          warmupTicks={100}
          cooldownTicks={50}
          d3AlphaDecay={0.05}
          d3VelocityDecay={0.3}
          enableNodeDrag={true}
          enableZoomInteraction={true}
          enablePanInteraction={true}
          nodeRelSize={2}
        />
      </div>

      {/* Legend */}
      <div className="graph-panel__legend">
        {legendItems.map((item, i) => (
          <div key={i} className="legend-item">
            <div
              className="legend-item__dot"
              style={{ backgroundColor: item.color }}
            />
            <span>{item.label}</span>
            {item.count && (
              <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>
                ({item.count})
              </span>
            )}
          </div>
        ))}
      </div>
    </>
  )
}
