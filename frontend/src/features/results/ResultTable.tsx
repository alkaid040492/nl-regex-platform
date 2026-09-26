import { useState } from "react";
import {
  Alert,
  Badge,
  Group,
  Loader,
  Pagination,
  Paper,
  ScrollArea,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { IconAlertCircle, IconTable } from "@tabler/icons-react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { getJobResult } from "../../api/endpoints";
import { errorMessage } from "../../api/client";

const PAGE_SIZES = ["25", "50", "100", "200"];

export function ResultTable({ jobId }: { jobId: string }) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [onlyMatched, setOnlyMatched] = useState(false);

  const result = useQuery({
    queryKey: ["result", jobId, page, pageSize, onlyMatched],
    queryFn: () => getJobResult(jobId, page, pageSize, onlyMatched),
    placeholderData: keepPreviousData,
  });

  const data = result.data;

  return (
    <Paper withBorder p="lg" radius="md" mt="md">
      <Stack gap="md">
        <Group justify="space-between">
          <Group gap="xs">
            <IconTable size={22} />
            <Title order={3}>Processed data</Title>
            {data && (
              <Badge variant="light">
                {data.total_rows.toLocaleString()} rows{onlyMatched ? " matched" : ""}
              </Badge>
            )}
            {result.isFetching && <Loader size="xs" />}
          </Group>
          <Group gap="md">
            <Switch
              size="sm"
              label="Only matched rows"
              checked={onlyMatched}
              onChange={(e) => {
                setOnlyMatched(e.currentTarget.checked);
                setPage(1);
              }}
            />
            <Select
              size="xs"
              w={110}
              data={PAGE_SIZES.map((s) => ({ value: s, label: `${s} / page` }))}
              value={String(pageSize)}
              onChange={(v) => {
                setPageSize(Number(v ?? 50));
                setPage(1);
              }}
            />
          </Group>
        </Group>

        {result.isLoading && (
          <Group gap="xs">
            <Loader size="sm" /> <Text size="sm">Loading first page…</Text>
          </Group>
        )}
        {result.error && (
          <Alert color="red" icon={<IconAlertCircle size={18} />} title="Could not load results">
            {errorMessage(result.error)}
          </Alert>
        )}

        {data && data.total_rows === 0 && (
          <Alert color="yellow" variant="light">
            {onlyMatched ? "No rows matched the pattern." : "The file contains no data rows."}
          </Alert>
        )}

        {data && data.rows.length > 0 && (
          <>
            <ScrollArea type="auto" offsetScrollbars>
              <Table striped highlightOnHover withTableBorder withColumnBorders fz="sm" style={{ minWidth: 600 }}>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th w={60}>#</Table.Th>
                    {data.columns.map((c) => (
                      <Table.Th key={c} style={{ whiteSpace: "nowrap" }}>
                        {c}
                      </Table.Th>
                    ))}
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {data.rows.map((row, i) => {
                    const matched = row._matched === true;
                    return (
                      <Table.Tr key={i} bg={matched ? "var(--mantine-color-teal-0)" : undefined}>
                        <Table.Td c="dimmed">{(data.page - 1) * data.page_size + i + 1}</Table.Td>
                        {data.columns.map((c) => {
                          const v = row[c];
                          const text = v === null || v === undefined ? "" : String(v);
                          return (
                            <Table.Td
                              key={c}
                              title={text}
                              style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                              c={text === "" ? "dimmed" : undefined}
                            >
                              {text === "" ? "∅" : text}
                            </Table.Td>
                          );
                        })}
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </ScrollArea>
            <Group justify="space-between">
              <Text size="xs" c="dimmed">
                Page {data.page} of {data.total_pages.toLocaleString()} · rows highlighted in green contained a match
              </Text>
              <Pagination total={data.total_pages} value={page} onChange={setPage} siblings={1} boundaries={1} />
            </Group>
          </>
        )}
      </Stack>
    </Paper>
  );
}
