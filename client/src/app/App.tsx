import { BrowserRouter, Route, Routes } from 'react-router';

import { FirstRunScreen } from '../features/upload/FirstRunScreen';
import { WorkspaceRoute } from './WorkspaceRoute';

/**
 * Three screens and only three: Upload, Chat, Data (decision D34).
 *
 * Chat is the product's main screen, so it is what a bare workspace URL resolves to —
 * `/w/{id}` and `/w/{id}/chat` are the same place (requirements section 3.2). Decision D30
 * records why this is React Router used declaratively rather than a generated route tree.
 *
 * A shared link lands on one of these routes carrying its token in the fragment, which is
 * consumed on arrival (decision D31).
 */
export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<FirstRunScreen />} />
        <Route path="/w/:workspaceId" element={<WorkspaceRoute />} />
        <Route path="/w/:workspaceId/chat" element={<WorkspaceRoute />} />
        <Route path="/w/:workspaceId/data" element={<WorkspaceRoute />} />
      </Routes>
    </BrowserRouter>
  );
}
