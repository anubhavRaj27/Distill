/**
 * Client-side intake rules. Requirement FR-03: unsupported types and oversized files are
 * rejected inline, before upload begins.
 *
 * This is a courtesy check, not a security boundary. The server sniffs content type from
 * the bytes and never trusts an extension (`server/app/pipeline/sniff.py`), which is the
 * authoritative decision. What this file buys is the user not waiting on a 20 MB upload to
 * be told it was never going to work. The two lists are therefore kept deliberately in
 * step with the server's `SUPPORTED_EXTENSIONS` and `max_upload_mb`.
 */

export const SUPPORTED_EXTENSIONS = [
  'pdf',
  'png',
  'jpg',
  'jpeg',
  'docx',
  'xlsx',
  'csv',
  'txt',
] as const;

export const MAX_FILE_BYTES = 20 * 1024 * 1024;

/** Mirrors the server's `max_files_per_upload`. */
export const MAX_FILES_PER_UPLOAD = 25;

/** Set on the file input so the picker filters before a person even chooses. */
export const ACCEPT_ATTRIBUTE = SUPPORTED_EXTENSIONS.map((ext) => `.${ext}`).join(',');

export type RejectionReason = 'unsupported-type' | 'too-large' | 'empty' | 'too-many';

export interface RejectedFile {
  file: File;
  reason: RejectionReason;
  /**
   * A complete sentence, ready to render. Errors in this product say what is wrong AND
   * what would work, because a person who has just been refused needs the second half more
   * than the first.
   */
  message: string;
}

export interface IntakeResult {
  accepted: File[];
  rejected: RejectedFile[];
}

export function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf('.');
  return dot === -1 ? '' : filename.slice(dot + 1).toLowerCase();
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const mb = bytes / (1024 * 1024);
  if (mb >= 1) return `${mb.toFixed(mb >= 10 ? 0 : 1)} MB`;
  return `${Math.round(bytes / 1024)} KB`;
}

const SUPPORTED_SENTENCE = `Distill reads ${SUPPORTED_EXTENSIONS.map((e) => e.toUpperCase()).join(', ')}.`;

/**
 * Partition a dropped or picked selection into what will be uploaded and what will not.
 *
 * Order is preserved and the whole selection is always examined, so a person dropping
 * twelve files sees every problem at once rather than one per attempt.
 */
export function sortIntake(files: readonly File[]): IntakeResult {
  const accepted: File[] = [];
  const rejected: RejectedFile[] = [];

  for (const file of files) {
    const extension = extensionOf(file.name);

    if (!(SUPPORTED_EXTENSIONS as readonly string[]).includes(extension)) {
      rejected.push({
        file,
        reason: 'unsupported-type',
        message: extension
          ? `Distill cannot read .${extension} files. ${SUPPORTED_SENTENCE}`
          : `This file has no extension, so its type could not be determined. ${SUPPORTED_SENTENCE}`,
      });
      continue;
    }

    if (file.size === 0) {
      rejected.push({
        file,
        reason: 'empty',
        message: 'This file is empty, so there is nothing to read.',
      });
      continue;
    }

    if (file.size > MAX_FILE_BYTES) {
      rejected.push({
        file,
        reason: 'too-large',
        message: `At ${formatBytes(file.size)} this is over the ${formatBytes(MAX_FILE_BYTES)} limit for a single file.`,
      });
      continue;
    }

    if (accepted.length >= MAX_FILES_PER_UPLOAD) {
      rejected.push({
        file,
        reason: 'too-many',
        message: `Only ${MAX_FILES_PER_UPLOAD} files can be uploaded at once. Add this one in the next batch.`,
      });
      continue;
    }

    accepted.push(file);
  }

  return { accepted, rejected };
}
