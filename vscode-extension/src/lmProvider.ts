import * as vscode from "vscode";
import { RouterClient, ChatMessage } from "./client";

/**
 * Registers hermes-router as a VS Code Language Model provider, so it appears in
 * Copilot Chat's model picker (and is usable by any vscode.lm consumer). The one
 * logical model "hermes-router" fans out across the router's free pool.
 */
export class HermesChatModelProvider implements vscode.LanguageModelChatProvider {
  constructor(private getClient: () => RouterClient) {}

  async provideLanguageModelChatInformation(
    _options: vscode.PrepareLanguageModelChatModelOptions,
    _token: vscode.CancellationToken
  ): Promise<vscode.LanguageModelChatInformation[]> {
    return [
      {
        id: "hermes-router",
        name: "hermes-router (free pool)",
        family: "hermes-router",
        version: "1.0.0",
        maxInputTokens: 32000,
        maxOutputTokens: 8192,
        capabilities: { toolCalling: false, imageInput: false },
      },
    ];
  }

  async provideLanguageModelChatResponse(
    _model: vscode.LanguageModelChatInformation,
    messages: readonly vscode.LanguageModelChatRequestMessage[],
    _options: vscode.ProvideLanguageModelChatResponseOptions,
    progress: vscode.Progress<vscode.LanguageModelResponsePart>,
    token: vscode.CancellationToken
  ): Promise<void> {
    const oai = messages.map(toOpenAI);
    await this.getClient().streamChat(oai, {
      onText: (delta) => progress.report(new vscode.LanguageModelTextPart(delta)),
      onAbort: (cancel) => token.onCancellationRequested(() => cancel()),
    });
  }

  async provideTokenCount(
    _model: vscode.LanguageModelChatInformation,
    text: string | vscode.LanguageModelChatRequestMessage,
    _token: vscode.CancellationToken
  ): Promise<number> {
    const s = typeof text === "string" ? text : messageText(text);
    return Math.ceil(s.length / 4); // cheap estimate (matches the router's char/4 fallback)
  }
}

/** Concatenate the text parts of a VS Code chat message. */
function messageText(msg: vscode.LanguageModelChatRequestMessage): string {
  return (msg.content || [])
    .map((p: any) => (p instanceof vscode.LanguageModelTextPart ? p.value : ""))
    .join("");
}

/** Translate a VS Code chat message to an OpenAI chat-completions message (v1: text only). */
function toOpenAI(msg: vscode.LanguageModelChatRequestMessage): ChatMessage {
  const role = msg.role === vscode.LanguageModelChatMessageRole.Assistant ? "assistant" : "user";
  return { role, content: messageText(msg) };
}
