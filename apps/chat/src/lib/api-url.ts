const DEFAULT_API_URL = "http://localhost:8001";

export function getApiUrl(): string {
  return (process.env.NEXT_PUBLIC_DOTAMIND_API_URL ?? DEFAULT_API_URL).replace(
    /\/$/,
    "",
  );
}
