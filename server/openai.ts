import OpenAI from "openai";

// OpenAI client using Replit AI Integrations (no API key required)
// Charges are billed to your Replit credits
export const openai = new OpenAI({
  apiKey: process.env.AI_INTEGRATIONS_OPENAI_API_KEY,
  baseURL: process.env.AI_INTEGRATIONS_OPENAI_BASE_URL,
});

// the newest OpenAI model is "gpt-5" which was released August 7, 2025
// Using gpt-4o for compatibility with AI integrations
const CHAT_MODEL = "gpt-4o";

export interface Citation {
  opinionId: string;
  caseName: string;
  appealNo: string;
  releaseDate: string;
  pageNumber: number;
  quote: string;
}

export interface ChatResponse {
  answer: string;
  citations: Citation[];
}

export async function generateChatResponse(
  userMessage: string,
  relevantChunks: Array<{
    chunkText: string;
    pageNumber: number | null;
    opinionId: string;
    caseName: string;
    appealNo: string;
    releaseDate: string;
  }>,
  conversationHistory: Array<{ role: "user" | "assistant"; content: string }>
): Promise<ChatResponse> {
  const systemPrompt = `You are an expert U.S. patent appellate practitioner specializing in Federal Circuit (CAFC) precedent. You must:

1. ONLY use information from the provided opinion excerpts below
2. For EVERY factual or legal claim, include a verbatim quote from the opinions with citation
3. If information is not found in the provided excerpts, say "NOT FOUND IN PROVIDED OPINIONS"
4. Write in a clear, well-reasoned, neutral legal tone
5. Format citations as: [Case Name, Appeal No., Date, p.X]

AVAILABLE OPINION EXCERPTS:
${relevantChunks.map((chunk, i) => `
--- EXCERPT ${i + 1} ---
Case: ${chunk.caseName}
Appeal No: ${chunk.appealNo}
Date: ${chunk.releaseDate}
Page: ${chunk.pageNumber || 'N/A'}
Text: "${chunk.chunkText}"
---
`).join('\n')}

Respond with a JSON object in this exact format:
{
  "answer": "Your comprehensive answer with inline citations like [Amgen v. Sanofi, 20-1074, 2021-02-11, p.12]",
  "citations": [
    {
      "opinionId": "id from excerpt",
      "caseName": "case name",
      "appealNo": "appeal number",
      "releaseDate": "date",
      "pageNumber": 1,
      "quote": "exact verbatim quote used"
    }
  ]
}`;

  const messages: Array<{ role: "system" | "user" | "assistant"; content: string }> = [
    { role: "system", content: systemPrompt },
    ...conversationHistory.slice(-10), // Keep last 10 messages for context
    { role: "user", content: userMessage },
  ];

  try {
    const response = await openai.chat.completions.create({
      model: CHAT_MODEL,
      messages,
      response_format: { type: "json_object" },
      max_tokens: 4096,
    });

    const content = response.choices[0]?.message?.content || '{"answer": "Error generating response", "citations": []}';
    
    try {
      const parsed = JSON.parse(content);
      return {
        answer: parsed.answer || "Error parsing response",
        citations: parsed.citations || [],
      };
    } catch {
      return {
        answer: content,
        citations: [],
      };
    }
  } catch (error) {
    console.error("OpenAI API error:", error);
    throw new Error(`Failed to generate response: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

export async function generateConversationTitle(firstMessage: string): Promise<string> {
  try {
    const response = await openai.chat.completions.create({
      model: CHAT_MODEL,
      messages: [
        {
          role: "system",
          content: "Generate a brief 3-6 word title for this legal research conversation. Respond with just the title, no quotes or punctuation.",
        },
        { role: "user", content: firstMessage },
      ],
      max_tokens: 20,
    });

    return response.choices[0]?.message?.content?.trim() || "New Research";
  } catch {
    return "New Research";
  }
}
