export const logger = {
  info(message: string, fields: Record<string, unknown> = {}): void {
    process.stdout.write(JSON.stringify({ level: "info", message, ...fields }) + "\n");
  },
  error(message: string, fields: Record<string, unknown> = {}): void {
    process.stderr.write(JSON.stringify({ level: "error", message, ...fields }) + "\n");
  },
};
