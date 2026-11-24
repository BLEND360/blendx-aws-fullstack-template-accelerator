import { Button, Result } from "antd";
import { Link } from "react-router";
import { messages } from "../messages";

export function NotFound() {
  return (
    <Result
      status="404"
      title={messages.notFoundTitle}
      extra={
        <Link to="/">
          <Button type="primary">{messages.notFoundLink}</Button>
        </Link>
      }
    />
  );
}
