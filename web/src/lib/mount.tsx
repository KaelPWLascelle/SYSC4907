import { type ReactNode, StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

/** Render into #root, failing loudly if the page does not have one. */
export function mount(app: ReactNode) {
  const root = document.getElementById('root');
  if (!root) throw new Error('Flicks: the page has no #root element');
  createRoot(root).render(<StrictMode>{app}</StrictMode>);
}
