import type { TroubleshootResponse } from "./types";

export async function troubleshoot(
  query: string,
  siisResponse?: string,
  signal?: AbortSignal,
): Promise<TroubleshootResponse> {
  const body: { query: string; siis_response?: string } = { query };
  if (siisResponse && siisResponse.trim() !== "") {
    body.siis_response = siisResponse;
  }
  const response = await fetch("/v1/troubleshoot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    throw new Error(`The engine returned an error (${response.status}).`);
  }
  return (await response.json()) as TroubleshootResponse;
}
