# TODO: AI/Agent Engineer
# 7-step flow:
# 1. Verify JWT → get user_id, user_role, user_department
# 2. get_context(user_id) → ConversationContext (summary + recent 5 msgs)
# 3. Build prompt: system + summary + recent_messages + user question
# 4. Call RAG Service → SearchResult list (Top-3)
# 5. Inject retrieved chunks vào prompt
# 6. Call Azure OpenAI GPT-4o Mini → stream response
# 7. save_message(user), save_message(assistant)
