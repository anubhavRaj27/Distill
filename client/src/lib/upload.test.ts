import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { makeTasks, runBatch, type UploadTask } from './upload';

/**
 * The uploader is the one place using `XMLHttpRequest` directly, so it is the one place
 * where a platform detail could silently stop reporting progress. These tests pin the
 * behaviour the upload screen depends on: bytes reported per file, a refusal surfaced as a
 * result rather than an exception, and one bad file not taking the batch with it.
 */

interface FakeXhrInstance {
  upload: { addEventListener: (type: string, fn: (e: unknown) => void) => void };
  addEventListener: (type: string, fn: () => void) => void;
  open: ReturnType<typeof vi.fn>;
  setRequestHeader: ReturnType<typeof vi.fn>;
  send: ReturnType<typeof vi.fn>;
  status: number;
  response: unknown;
  responseType: string;
}

/** Every instance the code under test constructed, in order. */
let instances: FakeXhrInstance[] = [];

/**
 * A minimal XHR stand-in. jsdom ships one, but it will not let a test drive
 * `upload.onprogress` deterministically, which is the whole point here.
 */
function installFakeXhr() {
  instances = [];

  class FakeXhr {
    status = 200;
    response: unknown = { accepted: [{ id: 'doc-1' }], rejected: [] };
    responseType = '';
    private handlers = new Map<string, Array<(e?: unknown) => void>>();
    private uploadHandlers = new Map<string, Array<(e?: unknown) => void>>();

    upload = {
      addEventListener: (type: string, fn: (e?: unknown) => void) => {
        const list = this.uploadHandlers.get(type) ?? [];
        list.push(fn);
        this.uploadHandlers.set(type, list);
      },
    };

    addEventListener = (type: string, fn: (e?: unknown) => void) => {
      const list = this.handlers.get(type) ?? [];
      list.push(fn);
      this.handlers.set(type, list);
    };

    open = vi.fn();
    setRequestHeader = vi.fn();

    send = vi.fn(() => {
      // Drive the lifecycle a real browser would: some bytes, then completion.
      queueMicrotask(() => {
        this.emitUpload('progress', { lengthComputable: true, loaded: 50, total: 100 });
        this.emitUpload('progress', { lengthComputable: true, loaded: 100, total: 100 });
        this.emit('load');
      });
    });

    private emit(type: string) {
      for (const fn of this.handlers.get(type) ?? []) fn();
    }
    private emitUpload(type: string, event: unknown) {
      for (const fn of this.uploadHandlers.get(type) ?? []) fn(event);
    }
  }

  vi.stubGlobal(
    'XMLHttpRequest',
    class extends FakeXhr {
      constructor() {
        super();
        instances.push(this as unknown as FakeXhrInstance);
      }
    },
  );
}

function makeFile(name: string, size = 100): File {
  const file = new File(['x'], name);
  Object.defineProperty(file, 'size', { value: size });
  return file;
}

async function collect(tasks: UploadTask[]) {
  const seen: Array<[string, Partial<UploadTask>]> = [];
  await runBatch({
    baseUrl: '',
    workspaceId: 'ws-1',
    token: 'tok',
    tasks,
    onChange: (key, patch) => {
      seen.push([key, patch]);
      Object.assign(
        tasks.find((task) => task.key === key)!,
        patch,
      );
    },
  });
  return seen;
}

beforeEach(installFakeXhr);
afterEach(() => vi.unstubAllGlobals());

describe('runBatch', () => {
  it('reports bytes as they are sent, per file', async () => {
    const tasks = makeTasks([makeFile('a.pdf')]);
    const seen = await collect(tasks);

    const progress = seen.filter(([, patch]) => patch.sent !== undefined && !patch.phase);
    expect(progress.map(([, patch]) => patch.sent)).toEqual([50, 100]);
  });

  it('moves a file through sending to ready and records its document id', async () => {
    const tasks = makeTasks([makeFile('a.pdf')]);
    await collect(tasks);

    expect(tasks[0]?.phase).toBe('ready');
    expect(tasks[0]?.documentId).toBe('doc-1');
  });

  it('sends one request per file so progress can be attributed', async () => {
    const tasks = makeTasks([makeFile('a.pdf'), makeFile('b.pdf'), makeFile('c.pdf')]);
    await collect(tasks);

    expect(instances).toHaveLength(3);
    for (const instance of instances) {
      expect(instance.open).toHaveBeenCalledWith(
        'POST',
        '/api/v1/workspaces/ws-1/documents',
      );
      expect(instance.setRequestHeader).toHaveBeenCalledWith('Authorization', 'Bearer tok');
    }
  });

  it('surfaces a file the server refused as a failure, not an exception', async () => {
    installFakeXhr();
    const original = globalThis.XMLHttpRequest;
    vi.stubGlobal(
      'XMLHttpRequest',
      class extends (original as unknown as { new (): FakeXhrInstance }) {
        constructor() {
          super();
          this.response = {
            accepted: [],
            rejected: [{ filename: 'a.key', code: 'unsupported', message: 'Not readable.' }],
          };
        }
      },
    );

    const tasks = makeTasks([makeFile('a.key')]);
    await collect(tasks);

    expect(tasks[0]?.phase).toBe('failed');
    expect(tasks[0]?.error).toBe('Not readable.');
  });

  it('lets the rest of a batch finish when one file fails', async () => {
    const tasks = makeTasks([makeFile('a.pdf'), makeFile('b.pdf')]);

    // Fail only the first request.
    let call = 0;
    const original = globalThis.XMLHttpRequest;
    vi.stubGlobal(
      'XMLHttpRequest',
      class extends (original as unknown as { new (): FakeXhrInstance }) {
        constructor() {
          super();
          if (call++ === 0) {
            this.status = 500;
            this.response = { detail: 'Storage is full.' };
          }
        }
      },
    );

    await collect(tasks);

    expect(tasks[0]?.phase).toBe('failed');
    expect(tasks[0]?.error).toBe('Storage is full.');
    expect(tasks[1]?.phase).toBe('ready');
  });
});
