import { describe, expect, it } from 'vitest';

import {
  MAX_FILES_PER_UPLOAD,
  MAX_FILE_BYTES,
  formatBytes,
  sortIntake,
} from './files';

/**
 * Requirement FR-03. These are the rules a person hits within seconds of arriving, so they
 * are worth pinning: a wrong answer here either uploads something the server will refuse
 * or refuses something the server would have accepted.
 */

function makeFile(name: string, size: number): File {
  const file = new File(['x'], name);
  // `File` in jsdom derives size from its parts, so it is overridden rather than faked
  // with a multi-megabyte string.
  Object.defineProperty(file, 'size', { value: size });
  return file;
}

describe('sortIntake', () => {
  it('accepts every supported format, whatever the case of the extension', () => {
    const files = [
      makeFile('invoice.pdf', 1000),
      makeFile('SCAN.PNG', 1000),
      makeFile('ledger.XLSX', 1000),
      makeFile('notes.txt', 1000),
    ];

    const { accepted, rejected } = sortIntake(files);

    expect(accepted).toHaveLength(4);
    expect(rejected).toHaveLength(0);
  });

  it('refuses an unsupported type and says what would work instead', () => {
    const { accepted, rejected } = sortIntake([makeFile('deck.key', 1000)]);

    expect(accepted).toHaveLength(0);
    expect(rejected[0]?.reason).toBe('unsupported-type');
    expect(rejected[0]?.message).toContain('.key');
    expect(rejected[0]?.message).toContain('PDF');
  });

  it('handles a file with no extension at all', () => {
    const { rejected } = sortIntake([makeFile('receipt', 1000)]);

    expect(rejected[0]?.reason).toBe('unsupported-type');
    expect(rejected[0]?.message).toContain('no extension');
  });

  it('refuses a file over the size limit and quotes its actual size', () => {
    const { rejected } = sortIntake([makeFile('huge.pdf', MAX_FILE_BYTES + 1)]);

    expect(rejected[0]?.reason).toBe('too-large');
    expect(rejected[0]?.message).toContain('20 MB');
  });

  it('accepts a file exactly on the limit', () => {
    const { accepted } = sortIntake([makeFile('exact.pdf', MAX_FILE_BYTES)]);

    expect(accepted).toHaveLength(1);
  });

  it('refuses an empty file rather than sending zero bytes to be parsed', () => {
    const { rejected } = sortIntake([makeFile('blank.pdf', 0)]);

    expect(rejected[0]?.reason).toBe('empty');
  });

  it('uploads what it can from a mixed selection instead of refusing the batch', () => {
    const { accepted, rejected } = sortIntake([
      makeFile('good.pdf', 1000),
      makeFile('bad.key', 1000),
      makeFile('also-good.csv', 1000),
    ]);

    expect(accepted.map((file) => file.name)).toEqual(['good.pdf', 'also-good.csv']);
    expect(rejected).toHaveLength(1);
  });

  it('caps a batch at the server limit and explains the overflow', () => {
    const files = Array.from({ length: MAX_FILES_PER_UPLOAD + 2 }, (_, index) =>
      makeFile(`doc-${index}.pdf`, 1000),
    );

    const { accepted, rejected } = sortIntake(files);

    expect(accepted).toHaveLength(MAX_FILES_PER_UPLOAD);
    expect(rejected).toHaveLength(2);
    expect(rejected[0]?.reason).toBe('too-many');
  });

  it('preserves order so the notice reads in the order files were dropped', () => {
    const { rejected } = sortIntake([
      makeFile('first.key', 1000),
      makeFile('ok.pdf', 1000),
      makeFile('second.key', 1000),
    ]);

    expect(rejected.map((entry) => entry.file.name)).toEqual(['first.key', 'second.key']);
  });
});

describe('formatBytes', () => {
  it('reads the way a person would say it', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2 KB');
    expect(formatBytes(1.5 * 1024 * 1024)).toBe('1.5 MB');
    expect(formatBytes(20 * 1024 * 1024)).toBe('20 MB');
  });
});
