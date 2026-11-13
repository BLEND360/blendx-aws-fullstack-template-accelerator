import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Empty, Flex, Form, Input, Typography } from "antd";
import { ApiError, asApiError } from "../../api/client";
import { messages } from "../../messages";
import { ApiErrorAlert } from "../../ui/ApiErrorAlert";
import { LoadingIndicator } from "../../ui/LoadingIndicator";
import { createItem, listItems } from "./api";
import type { NewItem } from "./api";

const FORM_FIELDS = ["name", "description"] as const;

/** The pattern to copy for a page of your own: a list, a create form, and the
 * three ways it can fail (nothing yet, a rejected field, the service down). */
export function ItemsPage() {
  const [form] = Form.useForm<NewItem>();
  const queryClient = useQueryClient();
  const items = useQuery({ queryKey: ["items"], queryFn: ({ signal }) => listItems(signal), retry: false });

  const create = useMutation({
    mutationFn: createItem,
    onSuccess: async () => {
      form.resetFields();
      await queryClient.invalidateQueries({ queryKey: ["items"] });
    },
    onError: (error) => {
      // A field error goes next to its field; what the user typed stays.
      const fields = error instanceof ApiError ? error.fields : [];
      form.setFields(
        FORM_FIELDS.flatMap((name) => {
          const mine = fields.filter((f) => f.location === `body.${name}`);
          return mine.length ? [{ name, errors: mine.map((f) => f.message) }] : [];
        }),
      );
    },
  });

  // Anything not tied to a form field (service down, unknown location) is shown as a general error.
  const createError = create.error ? asApiError(create.error) : null;
  const generalCreateError =
    createError && !createError.fields.some((f) => FORM_FIELDS.some((name) => f.location === `body.${name}`));

  return (
    <Flex vertical gap="large" style={{ maxWidth: 640 }}>
      <Typography.Title level={2} style={{ margin: 0 }}>
        {messages.itemsTitle}
      </Typography.Title>

      <Form form={form} layout="vertical" onFinish={(values) => create.mutate(values)} onValuesChange={() => form.setFields(FORM_FIELDS.map((name) => ({ name, errors: [] })))}>
        <Form.Item name="name" label={messages.itemName}>
          <Input />
        </Form.Item>
        <Form.Item name="description" label={messages.itemDescription}>
          <Input.TextArea rows={2} />
        </Form.Item>
        {createError && generalCreateError && (
          <Form.Item>
            <ApiErrorAlert error={createError} onRetry={() => create.variables && create.mutate(create.variables)} />
          </Form.Item>
        )}
        <Button type="primary" htmlType="submit" loading={create.isPending}>
          {messages.itemAdd}
        </Button>
      </Form>

      {items.isPending && <LoadingIndicator />}
      {items.isError && <ApiErrorAlert error={asApiError(items.error)} onRetry={() => void items.refetch()} />}
      {items.isSuccess && items.data.length === 0 && <Empty description={messages.itemsEmpty} />}
      {items.isSuccess && items.data.length > 0 && (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {items.data.map((item) => (
            <li key={item.id} style={{ padding: "8px 0" }}>
              <Typography.Text strong>{item.name}</Typography.Text>
              {item.description && (
                <>
                  <br />
                  <Typography.Text type="secondary">{item.description}</Typography.Text>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </Flex>
  );
}
