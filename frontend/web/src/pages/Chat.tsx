import { useClientConfig } from "../components/ConfigGate";
import { ChatPage } from "../features/chat/ChatPage";

/** The route's page: reads what the deployment says about itself and hands it to the chat. */
export function Chat() {
  const { replayMode } = useClientConfig();
  return <ChatPage replayMode={replayMode === true} />;
}
