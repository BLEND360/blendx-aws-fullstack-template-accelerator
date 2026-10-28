import { ArrowRightOutlined, DatabaseOutlined, MessageOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { Tag, Typography } from "antd";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { useAuth } from "../auth/useAuth";
import { useClientConfig } from "../components/ConfigGate";
import { messages } from "../messages";
import "../ui/design.css";

function greeting(hour: number): string {
  if (hour < 12) return messages.homeGreeting.morning;
  if (hour < 18) return messages.homeGreeting.afternoon;
  return messages.homeGreeting.evening;
}

function QuickCard({ to, icon, title, text }: { to: string; icon: ReactNode; title: string; text: string }) {
  return (
    <Link to={to} className="card">
      <span className="card-icon" aria-hidden>
        {icon}
      </span>
      <h3 className="card-title">{title}</h3>
      <p className="card-text">{text}</p>
      <span className="card-text card-more">
        <ArrowRightOutlined aria-hidden />
      </span>
    </Link>
  );
}

/** The landing page: where to go next, where this workspace runs, and the deployment's models
 * exactly as the API reports them (the pattern for reading client configuration). */
export function Home() {
  const config = useClientConfig();
  const { state } = useAuth();
  const local = state.status === "local";

  return (
    <div className="page">
      <header>
        <div className="page-kicker">{greeting(new Date().getHours())}</div>
        <Typography.Title level={2} className="page-title">
          {messages.homeTitle}
        </Typography.Title>
        <p className="page-sub">{messages.homeSubtitle}</p>
      </header>

      <section className="card-grid" aria-label={messages.homeTitle}>
        <QuickCard to="/chat" icon={<MessageOutlined />} title={messages.homeAssistantTitle} text={messages.homeAssistantText} />
        <QuickCard to="/items" icon={<DatabaseOutlined />} title={messages.homeItemsTitle} text={messages.homeItemsText} />
        <div className="card">
          <span className="card-icon" aria-hidden>
            <ThunderboltOutlined />
          </span>
          <h3 className="card-title">{messages.homeEnvironmentTitle}</h3>
          <p className="card-text">{local ? messages.homeEnvironmentLocal : messages.homeEnvironmentLive}</p>
        </div>
      </section>

      <section>
        <h3 className="section-title">{messages.modelsTitle}</h3>
        <ul className="card model-list">
          {config.allowedModelIds.map((id) => (
            <li key={id}>
              <Typography.Text code>{id}</Typography.Text>
              {id === config.defaultModelId && <Tag>{messages.defaultModel}</Tag>}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
