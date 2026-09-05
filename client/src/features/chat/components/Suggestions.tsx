import styled from 'styled-components';

/**
 * The opening move, for a person looking at a workspace they have just filled.
 *
 * Shown only on an empty thread. Once there is a conversation, the next question comes
 * from what the last answer said, and a row of generic prompts under it would be noise.
 */

const Panel = styled.section`
  display: flex;
  flex-direction: column;
  gap: ${({ theme }) => theme.space.md};
  align-items: flex-start;
`;

const Lead = styled.p`
  font-size: 13px;
  color: ${({ theme }) => theme.color.inkMuted};
`;

const Question = styled.button`
  appearance: none;
  max-width: 100%;
  padding: 10px 14px;

  font-family: inherit;
  font-size: 13px;
  line-height: 1.5;
  text-align: left;
  color: ${({ theme }) => theme.color.ink};
  background: ${({ theme }) => theme.color.paperRaised};
  border: 1px solid ${({ theme }) => theme.color.line};
  border-radius: ${({ theme }) => theme.radius.md};
  cursor: pointer;
  transition: background-color ${({ theme }) => theme.motion.quick};

  &:hover {
    background: ${({ theme }) => theme.color.paperSunken};
  }
`;

export interface SuggestionsProps {
  questions: string[];
  onPick: (question: string) => void;
}

export function Suggestions({ questions, onPick }: SuggestionsProps) {
  if (questions.length === 0) return null;

  return (
    <Panel aria-label="Suggested questions">
      <Lead>Drawn from what these documents turned out to contain:</Lead>
      {questions.map((question) => (
        <Question key={question} type="button" onClick={() => onPick(question)}>
          {question}
        </Question>
      ))}
    </Panel>
  );
}
