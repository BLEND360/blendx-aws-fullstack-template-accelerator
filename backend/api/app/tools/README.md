# Tools: how the agent gets capabilities

The model can call a tool. The tool runs **in this API process**, never in the browser or in the model. Only the
tools listed here can run; anything else the model asks for is refused (`not_enabled_for_session`).

## Add a tool in three steps

1. **Declare it in `builtin.py`.** Add an input model (its fields are the JSON schema the model sees and the
   validation of what it sends back), a handler, and an entry in `TOOLS`:

   ```python
   class WordCountInput(BaseModel):
       text: str = Field(max_length=10_000, description="Text to count words in.")

   def word_count(arguments: WordCountInput) -> dict[str, int]:
       return {"words": len(arguments.text.split())}

   TOOLS: list[Tool] = [
       Tool(
           id="current_time",
           # ... the existing entry stays here ...
       ),
       Tool(
           id="word_count",                      # [a-zA-Z0-9_-]{1,64}, unique
           label="Counting words",               # shown to the user while it runs
           description="Counts the words in a text.",  # shown to the model
           input_model=WordCountInput,
           handler=word_count,
       ),
   ]
   ```

   The `registry = ToolRegistry(TOOLS)` line at the end of the file must stay below the list.

2. **Allow it on the harness.** Add the id to `ALLOWED_TOOLS` in the infra project's harness definition (`infra/`).
   A test fails if the two lists differ, so a tool cannot be offered by the app and blocked by the harness, or the
   other way around.

3. **Redeploy the harness** with the "Harness" step of the root README: the allow list lives in the harness, so a
   code change alone is not enough.

## Rules the code already enforces

- The client names a tool by id only. Execution is resolved on the server (`ToolRegistry.run`).
- Bad input, a handler that raises, or an unknown id becomes `tool_failed`, which the model sees and can answer
  around. The request does not fail.
- A result the browser receives is capped at 16 KiB (`MAX_PUBLIC_RESULT_BYTES`); larger ones are sent as
  `{"truncated": true}`.

## Test it

`backend/api/tests/test_tools.py` shows the pattern: build a `ToolRegistry` with your tool and assert on `run`.
Keep the handler pure (no AWS calls) so the test needs nothing else.
