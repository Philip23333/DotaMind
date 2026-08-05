type InitializeThread = () => Promise<{ remoteId: string }>;

export async function createRunForInitializedThread<Run>({
  browserId,
  query,
  initializeThread,
  createRun,
}: {
  browserId: string;
  query: string;
  initializeThread: InitializeThread;
  createRun: (browserId: string, sessionId: string, query: string) => Promise<Run>;
}) {
  const { remoteId: sessionId } = await initializeThread();
  const run = await createRun(browserId, sessionId, query);
  return { run, sessionId };
}
