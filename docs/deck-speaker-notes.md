# Speaker notes — AWS Fullstack Template Accelerator

Deck: [aws-fullstack-template-deck.html](aws-fullstack-template-deck.html) · 7 slides · **10 minutes** of talk, the rest of the 30-minute slot for questions.

| #   | Slide                     | Time | Total |
| --- | ------------------------- | ---- | ----- |
| 1   | Title                     | 1:30 | 1:30  |
| 2   | Deployment model          | 1:45 | 3:15  |
| 3   | Stack                     | 1:00 | 4:15  |
| 4   | Harness integration layer | 2:15 | 6:30  |
| 5   | Work breakdown            | 1:00 | 7:30  |
| 6   | Sprint plan               | 1:15 | 8:45  |
| 7   | Decisions                 | 1:15 | 10:00 |

Talk about estimates and ranges, not hour counts.

---

# English

## 1 · Title (1:30)
> This is the plan for issue 1144, the AWS fullstack template. Today every new AWS app at Blend spends its first weeks on setup that isn't product: networking, IAM, CI/CD, SSO, and streaming an agent's answer to the browser. Snowflake has a template for this; AWS doesn't.
>
> The MVP already solves most of it, but it was built as a product, not as something to copy. So the proposal is to extract it into one template. A team clones it, sets name, account and region in one file, pushes, and gets a deployed, authenticated app with an agent already responding.

## 2 · Deployment model (1:45)
> CloudFront is the only thing exposed to the internet. It serves the React app from a private bucket and sends API calls to an internal load balancer. Behind it, FastAPI on Fargate talks to DynamoDB and the AgentCore harness. Nothing inside the box has a public address.
>
> That gives us three things for free: no proxy container, no CORS configuration, and a separate stack per layer, so rolling back the app never touches data. We also keep the MVP's hard lessons: one ordered deploy pipeline, a smoke test that checks the real response, and no AWS keys stored anywhere.

## 3 · Stack (1:00)
> Every choice here already runs in production in the MVP, so nothing is a bet. The one deliberate exception is using the platform's `agentcore` CLI for the harness, so it can move into the Hub later. At the bottom is what stays out of v1: we ship the harness itself and leave gateways and knowledge bases for later.

## 4 · Harness integration layer (2:15)
> This is the core of the proposal: how our backend calls the agent and streams the answer to the browser. Each message goes through five steps: check the user owns the session, load its frozen configuration, call the harness, run any tools it asks for, and stream the answer back.
>
> The list below is why we extract this instead of rewriting it. These are problems the MVP already solved, like bridging a blocking SDK into async or keeping a failing tool from crashing the conversation.
>
> Two rules matter here. The browser never sends anything executable, only text and ids. And no AWS error message ever reaches the user. Also, if a team already has a harness, they point to it by changing two config values, with no code changes.

## 5 · Work breakdown (1:00)
> Fifteen tickets: eleven core and four extensions, all filed with estimates and subtasks. Sprint 25 builds everything that runs locally. Sprint 26 deploys it and hardens it. Estimates are ranges, and the plan still fits even if every ticket lands at the top of its range.

## 6 · Sprint plan (1:15)
> This is the live plan; it updates as tickets move. Each row is a track: infra, backend, frontend and so on. The split follows the architecture: Sprint 25 is laptop, Sprint 26 is cloud. The demo lands in the second half of Sprint 26. The red line shows today, and anything behind plan gets flagged.

## 7 · Decisions (1:15)
> Only one decision blocks us, and not until Sprint 2: whether the template creates its own VPC or uses an existing one. We propose creating one by default.
>
> The idea is to begin the plan, start in Sprint 25, and settle the VPC question before Sprint 26. If anything runs late, we have buffer, and extensions are dropped first. Core is not negotiable. Happy to take questions.

---

## Likely questions
- **Why one repo?** The frontend already depends on the backend's stack. One repo makes that visible.
- **We already have a harness?** Change two values in `project.toml`. No code.
- **How many hours?** It's estimated per ticket with ranges, and the plan fits even at the top of every range. The detail is in each issue.
- **What if we're late?** Use the buffer first, then drop extensions. Core stays.

### Stack questions
Open with: *"None of these is new. It's what the MVP runs in production today."*

- **Why FastAPI?** The agent's answer streams token by token, and FastAPI is natively async, so one container holds many open streams. It's Python, the same language as our infrastructure and the AWS SDK. And it already runs in the MVP.
  - *Flask?* Not natively async, which is exactly what streaming needs.
  - *Django?* Too much we wouldn't use (ORM, admin, templates) for a thin API.
  - *Node?* It splits the backend from the infra language and means rewriting what the MVP already has.
- **Why React?** The Blend Design System is built on Ant Design, which is React, so apps look like Blend out of the box. The MVP frontend is already React.
  - *Next.js?* We don't need server rendering. The app is a static bundle on S3 behind CloudFront, so there's no server to run. Next.js would add one for no gain.
- **Why DynamoDB?** Conversation history lives in the harness's managed memory, not in our database. We only store metadata, like which sessions belong to which user. That's a key lookup, which is what DynamoDB does best. It also needs no network plumbing or connection pooling, costs nothing idle, and runs in the MVP.
  - *Why not Postgres?* A minimum monthly cost even when idle, private subnets, connection pooling and migrations, all to store session metadata. Data access is behind an interface, so a relational store can be added later without touching business logic. It's a follow-up, not a v1 need.
- **Why Fargate, not Lambda?** An agent's answer is a long, open stream. Lambda's time limits and cold starts hurt that. Fargate is a plain container with no servers to patch, and it's what the MVP runs.

Close with: *"We're not choosing technologies, we're packaging the ones that already work in production."*

---

# Español — qué se dice en cada slide

1. **Título:** hoy cada app AWS pierde semanas en configuración que no es producto. El MVP ya lo resuelve, pero no está hecho para copiarse. La propuesta es un template: clonar, configurar un archivo, hacer push, y queda una app desplegada con agente.
2. **Despliegue:** CloudFront es lo único público y todo lo demás es privado. Eso nos da sin costo: sin proxy, sin CORS y un stack por capa. Se conservan las lecciones del MVP: pipeline ordenado, smoke test real y sin llaves de AWS.
3. **Stack:** todo ya corre en producción. La excepción es el CLI `agentcore`, que permite llevar el harness al Hub. Gateways y knowledge bases quedan para después.
4. **Harness:** es el corazón de la propuesta, con 5 pasos por mensaje. Se extrae porque el MVP ya resolvió lo difícil. Hay dos reglas: el navegador nunca envía nada ejecutable, y ningún error de AWS llega al usuario. Usar un harness existente es cambiar dos valores.
5. **Tickets:** son 15 (11 core y 4 extensiones). El Sprint 1 es lo local y el Sprint 2 el despliegue. Las estimaciones son rangos, y el plan cabe aun en el peor caso.
6. **Plan:** es la vista en vivo. La división laptop/nube sigue la arquitectura, el demo cae en el Sprint 2, y la línea de hoy marca los atrasos.
7. **Decisiones:** solo la VPC bloquea, y no antes del Sprint 2. Recomendación: aprobar y arrancar en el Sprint 25. Si hay atraso se usa el colchón y se recortan extensiones; el core no se toca.

**Preguntas de stack (idea base: nada es nuevo, es lo que el MVP ya corre):**
- **FastAPI:** es async nativo, lo que el streaming necesita, y es Python como la infra y el SDK. No Flask (no es async), no Django (demasiado para una API delgada), no Node (partiría el lenguaje y obligaría a reescribir).
- **React:** el Design System de Blend está sobre Ant Design (React). No Next.js, porque la app es estática en S3 y no necesita servidor.
- **DynamoDB:** el historial vive en la memoria del harness, así que la base solo guarda metadatos (búsqueda por llave), sin red extra, y no cuesta nada inactiva. No Postgres, porque tiene costo mínimo, subnets, pooling y migraciones para muy poco; se puede agregar después.
- **Fargate:** el stream del agente es largo; Lambda tiene límite de tiempo y cold starts.
