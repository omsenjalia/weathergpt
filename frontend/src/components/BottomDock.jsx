import Dock from './bits/Dock'

const items = [
  { id: 'home', icon: '🌤️', label: 'Weather' },
  { id: 'chat', icon: '💬', label: 'Chat' },
  { id: 'voice', icon: '🎤', label: 'Voice' },
  { id: 'map', icon: '🗺️', label: 'Map' },
]

export default function BottomDock({ activeView, onNavigate }) {
  return (
    <Dock
      items={items.map((item) => ({
        ...item,
        onClick: () => onNavigate(item.id),
      }))}
      activeId={activeView}
    />
  )
}
