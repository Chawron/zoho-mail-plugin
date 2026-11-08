FROM python:3.12-slim

WORKDIR /app
COPY server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY server/zoho_mail_mcp.py ./zoho_mail_mcp.py

ENV MCP_HOST=0.0.0.0 MCP_PORT=8080
EXPOSE 8080
CMD ["python", "zoho_mail_mcp.py"]
