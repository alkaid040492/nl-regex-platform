import { useState } from "react";
import { Alert, Button, Group, Paper, PasswordInput, Stack, Text, TextInput, Title } from "@mantine/core";
import { IconAlertCircle, IconCloud, IconLock } from "@tabler/icons-react";
import { useMutation } from "@tanstack/react-query";
import { createConnection } from "../../api/endpoints";
import { ApiError, errorMessage } from "../../api/client";
import type { Connection } from "../../api/types";

interface Props {
  onConnected: (c: Connection) => void;
}

const ERROR_HINTS: Record<string, string> = {
  INVALID_CREDENTIALS: "Double-check the Access Key ID and Secret Access Key. Both are case-sensitive.",
  ACCESS_DENIED: "The key works but this IAM user cannot list this bucket. It needs s3:ListBucket and s3:GetObject.",
  BUCKET_NOT_FOUND: "No bucket with that name is visible to these credentials. Check spelling and region.",
  NETWORK_ERROR: "The server could not reach S3. Check the region or try again in a moment.",
};

export function ConnectForm({ onConnected }: Props) {
  const [accessKey, setAccessKey] = useState("");
  const [secretKey, setSecretKey] = useState("");
  const [bucket, setBucket] = useState("");
  const [region, setRegion] = useState("");

  const mutation = useMutation({
    mutationFn: createConnection,
    onSuccess: (conn) => {
      setSecretKey(""); // never keep the secret in component state longer than needed
      onConnected(conn);
    },
  });

  const err = mutation.error;
  const code = err instanceof ApiError ? err.code : undefined;

  return (
    <Paper withBorder p="lg" radius="md">
      <Stack gap="md">
        <Group gap="xs">
          <IconCloud size={22} />
          <Title order={3}>Connect to your S3 bucket</Title>
        </Group>
        <Text size="sm" c="dimmed">
          Credentials are validated against S3, encrypted, and kept in memory for two hours. They are never written to a
          database or log.
        </Text>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            mutation.mutate({
              access_key: accessKey.trim(),
              secret_key: secretKey.trim(),
              bucket: bucket.trim(),
              region: region.trim() || undefined,
            });
          }}
        >
          <Stack gap="sm">
            <TextInput
              label="AWS Access Key ID"
              placeholder="AKIA..."
              required
              value={accessKey}
              onChange={(e) => setAccessKey(e.currentTarget.value)}
              autoComplete="off"
              spellCheck={false}
            />
            <PasswordInput
              label="AWS Secret Access Key"
              placeholder="••••••••"
              required
              value={secretKey}
              onChange={(e) => setSecretKey(e.currentTarget.value)}
              autoComplete="off"
              leftSection={<IconLock size={16} />}
            />
            <Group grow align="flex-start">
              <TextInput
                label="Bucket name"
                placeholder="my-data-bucket"
                required
                value={bucket}
                onChange={(e) => setBucket(e.currentTarget.value.toLowerCase())}
                spellCheck={false}
              />
              <TextInput
                label="Region (optional)"
                placeholder="ap-northeast-1"
                value={region}
                onChange={(e) => setRegion(e.currentTarget.value)}
                spellCheck={false}
              />
            </Group>

            {err && (
              <Alert icon={<IconAlertCircle size={18} />} color="red" title={code ?? "Connection failed"} variant="light">
                <Text size="sm">{errorMessage(err)}</Text>
                {code && ERROR_HINTS[code] && (
                  <Text size="xs" c="dimmed" mt={4}>
                    {ERROR_HINTS[code]}
                  </Text>
                )}
              </Alert>
            )}

            <Group justify="flex-end">
              <Button type="submit" loading={mutation.isPending} disabled={!accessKey || !secretKey || !bucket}>
                Connect
              </Button>
            </Group>
          </Stack>
        </form>
      </Stack>
    </Paper>
  );
}
