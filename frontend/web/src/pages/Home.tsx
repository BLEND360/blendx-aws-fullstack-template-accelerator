import { Flex, Tag, Typography } from "antd";
import { useClientConfig } from "../components/ConfigGate";
import { messages } from "../messages";

/** Shows the deployment's models exactly as the API reports them: the pattern for reading client configuration. */
export function Home() {
  const config = useClientConfig();
  return (
    <>
      <Typography.Title level={2}>{messages.homeTitle}</Typography.Title>
      <Typography.Title level={4}>{messages.modelsTitle}</Typography.Title>
      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {config.allowedModelIds.map((id) => (
          <li key={id} style={{ padding: "8px 0" }}>
            <Flex gap="small" align="center">
              <Typography.Text code>{id}</Typography.Text>
              {id === config.defaultModelId && <Tag>{messages.defaultModel}</Tag>}
            </Flex>
          </li>
        ))}
      </ul>
    </>
  );
}
