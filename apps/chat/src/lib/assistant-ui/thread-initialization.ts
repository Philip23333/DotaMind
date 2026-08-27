type InitializeThread = () => Promise<{ remoteId: string }>;

export async function initializeThreadForMessage({
  initializeThread,
}: {
  initializeThread: InitializeThread;
}): Promise<string> {
  const { remoteId } = await initializeThread();
  return remoteId;
}
