import { describe, expect, it } from 'vitest';

import { parseSurface, readNumber, readProperty, resolvePath } from './model';

/**
 * The half of A2UI that makes agent-chosen presentation safe.
 *
 * Product principle 5 and decision D37: the model says where a figure lives, the server
 * puts the real figure there, and the client looks it up. These tests hold that the client
 * really does look it up — a renderer that quietly accepted an inline number would pass
 * every visual check and break the guarantee the whole architecture exists for.
 */

/** A surface shaped exactly as `server/app/a2ui/build.py` emits one. */
const BAR_SURFACE = [
  { version: 'v0.9', createSurface: { surfaceId: 's1', catalogId: 'distill.app:v2' } },
  {
    version: 'v0.9',
    updateDataModel: {
      surfaceId: 's1',
      path: '/result',
      value: {
        title: 'Spend by vendor (Q3)',
        unit: 'USD',
        rows: [
          { label: 'Argosy Logistics', value: 184200, record_ids: ['rec-1'] },
          { label: 'Northfield Supply', value: 142900, record_ids: ['rec-2'] },
        ],
        total: 327100,
      },
    },
  },
  {
    version: 'v0.9',
    updateComponents: {
      surfaceId: 's1',
      components: [
        { id: 'root', component: 'Column', children: ['title', 'visual'] },
        { id: 'title', component: 'Text', text: { path: '/result/title' }, variant: 'h3' },
        {
          id: 'visual',
          component: 'BarChart',
          rows: { path: '/result/rows' },
          xKey: 'label',
          yKey: 'value',
          unit: 'USD',
        },
      ],
    },
  },
];

describe('resolvePath', () => {
  const data = { result: { rows: [{ label: 'Argosy', value: 184200 }] } };

  it('walks objects and indexes arrays, which is the shape Metric binds to', () => {
    expect(resolvePath(data, '/result/rows/0/value')).toBe(184200);
    expect(resolvePath(data, '/result/rows/0/label')).toBe('Argosy');
  });

  it('returns undefined for a path that leads nowhere rather than throwing', () => {
    // A surface that half-renders is more use than a card that takes the answer down.
    expect(resolvePath(data, '/result/rows/9/value')).toBeUndefined();
    expect(resolvePath(data, '/nothing/here')).toBeUndefined();
  });
});

describe('parseSurface', () => {
  it('folds the three messages into a data model and a component tree', () => {
    const parsed = parseSurface(BAR_SURFACE)!;

    expect(parsed.catalogId).toBe('distill.app:v2');
    expect(parsed.rootId).toBe('root');
    expect(parsed.components.size).toBe(3);
  });

  it('resolves a bound property through the data model, never off the component', () => {
    const parsed = parseSurface(BAR_SURFACE)!;
    const title = parsed.components.get('title')!;
    const chart = parsed.components.get('visual')!;

    expect(readProperty(title, 'text', parsed.data)).toBe('Spend by vendor (Q3)');

    const rows = readProperty(chart, 'rows', parsed.data) as { value: number }[];
    expect(rows.map((row) => row.value)).toEqual([184200, 142900]);
  });

  it('drops a component the catalog does not contain', () => {
    /*
     * Requirement A2-05. The catalog is closed, and this is the line between "the agent
     * chooses the presentation" and "the agent injects markup". An unknown name is dropped
     * here so nothing downstream has to decide what to do with one.
     */
    const parsed = parseSurface([
      {
        updateComponents: {
          surfaceId: 's1',
          components: [
            { id: 'root', component: 'Column', children: ['bad', 'ok'] },
            { id: 'bad', component: 'ScriptTag', src: 'https://example.invalid/x.js' },
            { id: 'ok', component: 'Text', text: 'kept' },
          ],
        },
      },
    ])!;

    expect(parsed.components.has('bad')).toBe(false);
    expect(parsed.components.has('ok')).toBe(true);
  });

  it('returns null when there is nothing renderable', () => {
    expect(parseSurface([])).toBeNull();
    expect(parseSurface([{ createSurface: { surfaceId: 's1' } }])).toBeNull();
  });
});

describe('readNumber', () => {
  it('accepts the string form money arrives in', () => {
    // Decimals cross the wire as strings so they do not lose precision on the way.
    expect(readNumber('184200.50')).toBe(184200.5);
    expect(readNumber(42)).toBe(42);
  });

  it('refuses anything that is not a finite number', () => {
    expect(readNumber('not a number')).toBeNull();
    expect(readNumber(null)).toBeNull();
    expect(readNumber(Number.POSITIVE_INFINITY)).toBeNull();
  });
});

describe('the fallback path', () => {
  it('can always reach the rows, because the server always writes the data model', () => {
    /*
     * What `SurfaceBoundary` relies on when a surface will not render: the components may
     * be unusable, but `updateDataModel` carried the evaluated result, so the figures are
     * still there to be listed. This is why the fallback is a table of real numbers rather
     * than an apology.
     */
    const parsed = parseSurface(BAR_SURFACE)!;
    const rows = resolvePath(parsed.data, '/result/rows') as { label: string }[];

    expect(rows.map((row) => row.label)).toEqual(['Argosy Logistics', 'Northfield Supply']);
  });
});
