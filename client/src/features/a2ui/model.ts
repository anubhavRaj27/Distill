/**
 * Reading an A2UI message array into something renderable. Requirement A2-02, decision D39.
 *
 * The server sends three messages per surface (`server/app/a2ui/build.py`): `createSurface`
 * names the catalog, `updateDataModel` writes the **server-computed** result at `/result`,
 * and `updateComponents` emits components whose properties are *path bindings* into it.
 *
 * The separation is the entire safety argument of decision D37, and it only holds if the
 * client honours it. A component says "my value is at `/result/rows/0/value`"; this module
 * looks that path up in the data model the server wrote. No figure a surface renders ever
 * passed through the model, so letting the agent choose the presentation cannot let it
 * choose the numbers.
 *
 * The catalog is closed (`server/app/a2ui/catalog.py`): four custom components plus five
 * layout and text ones. Anything else is dropped rather than rendered, which is what makes
 * an agent-authored surface a rendering problem and not an injection surface (A2-05).
 */

export const KNOWN_COMPONENTS = [
  'Column',
  'Row',
  'Text',
  'Card',
  'Divider',
  'Metric',
  'BarChart',
  'LineChart',
  'ResultTable',
] as const;

export type ComponentName = (typeof KNOWN_COMPONENTS)[number];

export interface SurfaceComponent {
  id: string;
  component: ComponentName;
  children?: string[];
  [property: string]: unknown;
}

export interface ParsedSurface {
  surfaceId: string;
  catalogId: string;
  data: unknown;
  /** By id, so a `children` list resolves without a scan. */
  components: Map<string, SurfaceComponent>;
  rootId: string;
}

/** A property that is `{ path: "/result/…" }` rather than a literal. */
interface Binding {
  path: string;
}

function isBinding(value: unknown): value is Binding {
  return (
    typeof value === 'object' &&
    value !== null &&
    'path' in value &&
    typeof (value as Binding).path === 'string'
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Walk a `/`-separated path into the data model.
 *
 * Numeric segments index arrays, which is what makes `/result/rows/0/value` — the shape
 * `Metric` binds to — resolve without a special case. A path that leads nowhere returns
 * undefined and the component renders its absent state; it never throws, because a surface
 * that half-renders is more use than a card that takes the answer down with it.
 */
export function resolvePath(data: unknown, path: string): unknown {
  const segments = path.split('/').filter(Boolean);
  let current: unknown = data;

  for (const segment of segments) {
    if (Array.isArray(current)) {
      const index = Number(segment);
      if (!Number.isInteger(index)) return undefined;
      current = current[index];
      continue;
    }
    if (!isRecord(current)) return undefined;
    current = current[segment];
  }

  return current;
}

/** A component property, with any binding already resolved against the data model. */
export function readProperty(
  component: SurfaceComponent,
  name: string,
  data: unknown,
): unknown {
  const raw = component[name];
  return isBinding(raw) ? resolvePath(data, raw.path) : raw;
}

/**
 * Write `value` at `path` into a data model, returning the new model.
 *
 * The server only ever writes the whole of `/result` in one message, so this is not doing
 * deep merges in practice. It is written generally anyway because the protocol allows a
 * narrower path, and a client that silently ignored one would drop data.
 */
function writeAtPath(model: unknown, path: string, value: unknown): unknown {
  const segments = path.split('/').filter(Boolean);
  if (segments.length === 0) return value;

  const root: Record<string, unknown> = isRecord(model) ? { ...model } : {};
  let cursor = root;

  for (let index = 0; index < segments.length - 1; index += 1) {
    const key = segments[index]!;
    const next = cursor[key];
    const branch: Record<string, unknown> = isRecord(next) ? { ...next } : {};
    cursor[key] = branch;
    cursor = branch;
  }

  cursor[segments[segments.length - 1]!] = value;
  return root;
}

const COMPONENT_SET: ReadonlySet<string> = new Set(KNOWN_COMPONENTS);

/**
 * Fold a message array into one surface, or null when there is nothing renderable.
 *
 * Null covers an empty array, a surface with no components, and a surface whose root is
 * missing. Each of those is a server bug rather than a user-visible situation, and the
 * caller's answer to all three is the same: draw the prose and no card.
 */
export function parseSurface(messages: unknown[]): ParsedSurface | null {
  let surfaceId = '';
  let catalogId = '';
  let data: unknown = {};
  const components = new Map<string, SurfaceComponent>();

  for (const message of messages) {
    if (!isRecord(message)) continue;

    const create = message.createSurface;
    if (isRecord(create)) {
      surfaceId = typeof create.surfaceId === 'string' ? create.surfaceId : surfaceId;
      catalogId = typeof create.catalogId === 'string' ? create.catalogId : catalogId;
      continue;
    }

    const update = message.updateDataModel;
    if (isRecord(update) && typeof update.path === 'string') {
      data = writeAtPath(data, update.path, update.value);
      continue;
    }

    const components_ = message.updateComponents;
    if (isRecord(components_) && Array.isArray(components_.components)) {
      for (const entry of components_.components) {
        if (!isRecord(entry)) continue;
        const { id, component } = entry;
        if (typeof id !== 'string' || typeof component !== 'string') continue;
        // The catalog is closed. An unknown component name is dropped here, so nothing
        // downstream has to decide what to do with one.
        if (!COMPONENT_SET.has(component)) continue;

        components.set(id, {
          ...(entry as Record<string, unknown>),
          id,
          component: component as ComponentName,
          children: Array.isArray(entry.children)
            ? entry.children.filter((child): child is string => typeof child === 'string')
            : undefined,
        });
      }
    }
  }

  if (components.size === 0) return null;

  // The builder always names its root `root`; falling back to the first component keeps a
  // hand-written or future surface renderable rather than blank.
  const rootId = components.has('root') ? 'root' : [...components.keys()][0]!;

  return { surfaceId, catalogId, data, components, rootId };
}

/** A row inside a chart or result table, as the server's `QueryResult` sends it. */
export interface SurfaceRow {
  label?: unknown;
  value?: unknown;
  record_ids?: string[];
  [column: string]: unknown;
}

export function readRows(value: unknown): SurfaceRow[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord) as SurfaceRow[];
}

/** A number from the data model, or null. Strings are accepted: money arrives as one. */
export function readNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}
