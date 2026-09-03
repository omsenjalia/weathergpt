import { Sun, MessageSquare, Map } from 'lucide-react'
import Dock from './bits/Dock'

const items = [
  { id: 'home', icon: Sun, label: 'Weather' },
  { id: 'chat', icon: MessageSquare, label: 'Chat' },
  { id: 'map', icon: Map, label: 'Map' },
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
