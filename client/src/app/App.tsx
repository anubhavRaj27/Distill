import { BrowserRouter, Route, Routes } from 'react-router';

import { Toasts } from '../ui/Toasts';
import { ChatScreen } from '../features/chat/ChatScreen';
import { DataScreen } from '../features/data/DataScreen';
import { UploadScreen } from '../features/upload/UploadScreen';

/**
 * Three screens and only three: Upload, Chat, Data (decision D34).
 *
 * Chat is the product's main screen, so it is what a bare workspace URL resolves to —
 * `/w/{id}` and `/w/{id}/chat` are the same place (requirements section 3.2). Decision D30
 * records why this is React Router used declaratively rather than a generated route tree.
 *
 * A shared link lands on one of these routes carrying its token in the fragment, which is
 * consumed on arrival (decision D31).
 *
 * `/` and `/w/{id}/upload` are one component. They are the same screen in two states — the
 * name, a way to put documents in, and whatever is already in — and the route is what says
 * which. See decision D72.
 */
export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<UploadScreen />} />
        <Route path="/w/:workspaceId/upload" element={<UploadScreen />} />
        <Route path="/w/:workspaceId" element={<ChatScreen />} />
        <Route path="/w/:workspaceId/chat" element={<ChatScreen />} />
        <Route path="/w/:workspaceId/data" element={<DataScreen />} />
      </Routes>

      {/*
        Above the routes, so a confirmation raised by a screen on its way out is still
        there once the next screen has arrived. Decision D73.
      */}
      <Toasts />
    </BrowserRouter>
  );
}
