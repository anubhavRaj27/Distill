import { BrowserRouter, Route, Routes } from 'react-router';

import { FirstRunScreen } from '../features/upload/FirstRunScreen';
import { WorkspaceRoute } from './WorkspaceRoute';

/**
 * Routes. Decision D30 records why this is React Router in declarative mode rather than a
 * file-based or type-generated router: the application has a handful of routes, and a
 * build step to generate a route tree would cost more than it returns at this size.
 *
 * `/w/:workspaceId` is where a shared link lands. The token rides in the fragment of that
 * link and is consumed on arrival (decision D31).
 */
export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<FirstRunScreen />} />
        <Route path="/w/:workspaceId" element={<WorkspaceRoute />} />
      </Routes>
    </BrowserRouter>
  );
}
