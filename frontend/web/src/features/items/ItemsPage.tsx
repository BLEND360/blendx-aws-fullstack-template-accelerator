import {
  CalendarOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  EditOutlined,
  FileTextOutlined,
  MoreOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Dropdown, Form, Input, Modal, Typography } from "antd";
import { useState } from "react";
import { ApiError, asApiError } from "../../api/client";
import { messages } from "../../messages";
import { ApiErrorAlert } from "../../ui/ApiErrorAlert";
import "../../ui/design.css";
import { LoadingIndicator } from "../../ui/LoadingIndicator";
import { createItem, deleteItem, listItems, updateItem } from "./api";
import type { Item, NewItem } from "./api";
import "./items.css";

const FORM_FIELDS = ["name", "description"] as const;

function formatDate(iso: string): string | null {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date.toLocaleDateString(undefined, { dateStyle: "medium" });
}

/** Create or edit one item. A field error goes next to its field and what the user typed stays;
 * anything else (service down) is a general error with a retry. */
function ItemForm({ item, onDone }: { item: Item | null; onDone: () => void }) {
  const [form] = Form.useForm<NewItem>();
  const queryClient = useQueryClient();

  const save = useMutation({
    mutationFn: (values: NewItem) => (item ? updateItem(item.id, values) : createItem(values)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["items"] });
      onDone();
    },
    onError: (error) => {
      const fields = error instanceof ApiError ? error.fields : [];
      form.setFields(
        FORM_FIELDS.flatMap((name) => {
          const mine = fields.filter((f) => f.location === `body.${name}`);
          return mine.length ? [{ name, errors: mine.map((f) => f.message) }] : [];
        }),
      );
    },
  });

  const error = save.error ? asApiError(save.error) : null;
  const general = error && !error.fields.some((f) => FORM_FIELDS.some((name) => f.location === `body.${name}`));

  return (
    <Form
      form={form}
      layout="vertical"
      initialValues={item ? { name: item.name, description: item.description ?? "" } : undefined}
      onFinish={(values) => save.mutate(values)}
      onValuesChange={() => form.setFields(FORM_FIELDS.map((name) => ({ name, errors: [] })))}
    >
      <Form.Item name="name" label={messages.itemName} extra={messages.itemNameHelp}>
        <Input autoFocus size="large" />
      </Form.Item>
      <Form.Item name="description" label={messages.itemDescription} extra={messages.itemDescriptionHelp}>
        <Input.TextArea rows={4} />
      </Form.Item>
      {error && general && (
        <Form.Item>
          <ApiErrorAlert error={error} onRetry={() => save.variables && save.mutate(save.variables)} />
        </Form.Item>
      )}
      <div className="item-form-actions">
        <Button onClick={onDone}>{messages.itemCancel}</Button>
        <Button type="primary" htmlType="submit" loading={save.isPending}>
          {item ? messages.itemSave : messages.itemCreate}
        </Button>
      </div>
    </Form>
  );
}

function ItemCard({ item, onEdit, onDelete }: { item: Item; onEdit: () => void; onDelete: () => void }) {
  const created = formatDate(item.createdAt);
  return (
    <article className="card card--interactive item-card">
      <div className="item-card-top">
        <span className="card-icon" aria-hidden>
          <FileTextOutlined />
        </span>
        <Dropdown
          trigger={["click"]}
          placement="bottomRight"
          menu={{
            items: [
              { key: "edit", label: messages.itemEdit, icon: <EditOutlined />, onClick: onEdit },
              { key: "delete", label: messages.itemDelete, icon: <DeleteOutlined />, danger: true, onClick: onDelete },
            ],
          }}
        >
          <Button type="text" shape="circle" icon={<MoreOutlined />} aria-label={`${messages.itemActions}: ${item.name}`} />
        </Dropdown>
      </div>
      <h3 className="card-title">{item.name}</h3>
      {item.description && <p className="card-text item-card-desc">{item.description}</p>}
      {created && (
        <span className="item-card-date">
          <CalendarOutlined aria-hidden /> {messages.itemCreated} {created}
        </span>
      )}
    </article>
  );
}

/** The pattern to copy for a page of your own: a list, a create/edit dialog, a delete confirmation
 * and the ways it can fail (nothing yet, a rejected field, the service down). */
export function ItemsPage() {
  const queryClient = useQueryClient();
  const items = useQuery({ queryKey: ["items"], queryFn: ({ signal }) => listItems(signal), retry: false });

  const [editing, setEditing] = useState<{ open: boolean; item: Item | null }>({ open: false, item: null });
  const [deleting, setDeleting] = useState<Item | null>(null);

  const remove = useMutation({
    mutationFn: (item: Item) => deleteItem(item.id),
    onSuccess: async () => {
      setDeleting(null);
      await queryClient.invalidateQueries({ queryKey: ["items"] });
    },
  });

  const open = () => setEditing({ open: true, item: null });
  const askDelete = (item: Item) => {
    remove.reset();
    setDeleting(item);
  };
  const close = () => setEditing((current) => ({ ...current, open: false }));

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="page-kicker">{messages.homeItemsTitle}</div>
          <Typography.Title level={2} className="page-title">
            {messages.itemsTitle}
          </Typography.Title>
          <p className="page-sub">{messages.itemsSubtitle}</p>
        </div>
        <Button type="primary" size="large" icon={<PlusOutlined aria-hidden />} onClick={open}>
          {messages.itemAdd}
        </Button>
      </header>

      {items.isPending && <LoadingIndicator />}
      {items.isError && <ApiErrorAlert error={asApiError(items.error)} onRetry={() => void items.refetch()} />}

      {items.isSuccess && items.data.length === 0 && (
        <div className="empty">
          <span className="empty-icon" aria-hidden>
            <DatabaseOutlined />
          </span>
          <h3>{messages.itemsEmpty}</h3>
          <p>{messages.itemsEmptyHint}</p>
          <Button type="primary" icon={<PlusOutlined aria-hidden />} onClick={open}>
            {messages.itemsCreateFirst}
          </Button>
        </div>
      )}

      {items.isSuccess && items.data.length > 0 && (
        <section aria-label={messages.itemsYours}>
          <h3 className="section-title">
            {messages.itemsYours} · {items.data.length}
          </h3>
          <div className="card-grid">
            {items.data.map((item) => (
              <ItemCard key={item.id} item={item} onEdit={() => setEditing({ open: true, item })} onDelete={() => askDelete(item)} />
            ))}
          </div>
        </section>
      )}

      <Modal
        open={editing.open}
        title={editing.item ? messages.itemEditTitle : messages.itemNewTitle}
        footer={null}
        destroyOnHidden
        onCancel={close}
        width={520}
      >
        <ItemForm item={editing.item} onDone={close} />
      </Modal>

      <Modal
        open={deleting !== null}
        title={messages.itemDeleteTitle}
        okText={messages.itemDelete}
        cancelText={messages.itemCancel}
        okButtonProps={{ danger: true, loading: remove.isPending }}
        onOk={() => deleting && remove.mutate(deleting)}
        onCancel={() => setDeleting(null)}
        destroyOnHidden
      >
        <p style={{ margin: 0 }}>{messages.itemDeleteText}</p>
        {remove.isError && <ApiErrorAlert error={asApiError(remove.error)} onRetry={() => deleting && remove.mutate(deleting)} />}
      </Modal>
    </div>
  );
}
