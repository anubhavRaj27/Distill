import { FileSpreadsheet, FileText, Image as ImageIcon } from 'lucide-react';
import type { ComponentType } from 'react';
import styled, { keyframes } from 'styled-components';

/**
 * The argument of the product, made before a person has uploaded anything: six documents
 * that plainly disagree with each other — three formats, six naming conventions — fall
 * through a funnel and settle as one small ruled table.
 *
 * The filenames are deliberately concrete rather than generic paper. "invoice_0417.pdf"
 * beside "vendor_terms.docx" beside "spend_q3.xlsx" says *heterogeneous* in a way that four
 * blank rectangles cannot, and heterogeneity is the problem this product exists to solve.
 *
 * Decorative: hidden from assistive technology, with the caption beneath carrying the same
 * meaning in words.
 */

const settle = keyframes`
  from { opacity: 0; transform: translateY(-8px); }
  to   { opacity: 1; transform: translateY(0); }
`;

const arrive = keyframes`
  from { opacity: 0; }
  to   { opacity: 1; }
`;

const Figure = styled.figure`
  margin: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
`;

const Stage = styled.div`
  position: relative;
  width: 760px;
  height: 274px;
  max-width: 100%;
`;

/**
 * Each card is placed and rotated by inline style, and the entrance animation runs on this
 * wrapper. Keeping the two apart is not a stylistic choice: a CSS transform animation on an
 * element overrides its other transforms outright rather than composing with them, and with
 * `fill-mode: both` that loss is permanent. Rotation therefore lives on the inner element.
 */
const Card = styled.div`
  position: absolute;
  animation: ${settle} ${({ theme }) => theme.motion.settle} both;
`;

const CardFace = styled.div`
  display: flex;
  align-items: center;
  gap: ${({ theme }) => theme.space.sm};
  padding: 8px 12px;

  text-align: left;
  background: ${({ theme }) => theme.color.paperRaised};
  border-radius: ${({ theme }) => theme.radius.sm};
  box-shadow: ${({ theme }) => theme.shadow.card};

  svg {
    flex-shrink: 0;
    color: ${({ theme }) => theme.color.ink};
  }
`;

const Filename = styled.span`
  font-size: 11px;
  line-height: 1.3;
  color: ${({ theme }) => theme.color.inkMuted};
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
`;

const Funnel = styled.svg`
  position: absolute;
  top: 116px;
  left: 50%;
  transform: translateX(-50%);
  width: 330px;
  height: 142px;
  color: ${({ theme }) => theme.color.ink};
  animation: ${arrive} ${({ theme }) => theme.motion.settle} 380ms both;
`;

const Caption = styled.figcaption`
  margin-top: ${({ theme }) => theme.space.sm};
  font-size: 12px;
  color: ${({ theme }) => theme.color.inkMuted};
  text-align: center;
`;

interface Scrap {
  name: string;
  icon: ComponentType<{ size?: number | string }>;
  /** Placement within the 760×274 stage, mirroring the design's absolute coordinates. */
  style: React.CSSProperties;
  rotate: number;
  width: number;
}

const SCRAPS: Scrap[] = [
  { name: 'invoice_0417.pdf', icon: FileText, style: { left: 92, top: 18 }, rotate: -5, width: 154 },
  { name: 'vendor_terms.docx', icon: FileText, style: { left: 276, top: 2 }, rotate: 3, width: 154 },
  { name: 'spend_q3.xlsx', icon: FileSpreadsheet, style: { right: 94, top: 22 }, rotate: -2, width: 146 },
  { name: 'receipt_scan.jpg', icon: ImageIcon, style: { left: 38, top: 83 }, rotate: 4, width: 144 },
  { name: 'contract_v2.pdf', icon: FileText, style: { right: 43, top: 82 }, rotate: -6, width: 146 },
  { name: 'notes.txt', icon: FileText, style: { left: 300, top: 100 }, rotate: 5, width: 128 },
];

export function DistillationMark() {
  return (
    <Figure>
      <Stage aria-hidden="true">
        {SCRAPS.map((scrap, index) => {
          const Icon = scrap.icon;
          return (
            <Card
              key={scrap.name}
              style={{ ...scrap.style, animationDelay: `${index * 60}ms` }}
            >
              <CardFace
                style={{ width: scrap.width, transform: `rotate(${scrap.rotate}deg)` }}
              >
                <Icon size={14} />
                <Filename>{scrap.name}</Filename>
              </CardFace>
            </Card>
          );
        })}

        <Funnel viewBox="0 0 330 142" fill="none" focusable="false">
          {/* The funnel itself: wide mouth, narrow throat. */}
          <path
            d="M12 4H318L204 106H126L12 4Z"
            stroke="currentColor"
            strokeOpacity="0.46"
            strokeWidth="1.2"
          />
          {/* What comes out the bottom: one small table. */}
          <path
            d="M126 106H204V116H126V106Z"
            stroke="currentColor"
            strokeOpacity="0.56"
            strokeWidth="1.2"
          />
          <path
            d="M132 109H198 M132 113H198 M132 117H198"
            stroke="currentColor"
            strokeOpacity="0.5"
            strokeWidth="1"
          />
        </Funnel>
      </Stage>

      <Caption>Scattered documents settle into one structured table.</Caption>
    </Figure>
  );
}
