"""数据库表结构(SQLAlchemy 2.0 声明式模型)。

设计意图:
    本文件照搬原 morhpic 项目 lib/db/schema.ts 的六张表,字段一一对应,
    以保证行为兼容。核心设计点:

      1. messages 与 parts 分离
         一条消息(message)只记角色/时间等元信息;它的具体内容拆成若干
         部件(part)——文本、推理过程、文件、来源链接、工具调用等。
         这正是 Vercel AI SDK 的 UIMessage 结构:一条消息 = 多个有序 part。
         parts 表用"宽列"存所有可能的 part 类型(每个类型占一组可空列),
         用 type 列区分当前行是哪种 part。这样一张表装下所有部件类型,
         代价是每行有大量空列——换来查询与写入的简单。

      2. 行级安全(RLS)
         原项目在 PostgreSQL 层用 RLS 策略保证"用户只能看到自己的聊天"。
         Ryoshi 后端是单服务直连数据库,鉴权在应用层做(查询时带 user_id 过滤),
         因此这里只建模表结构,RLS 策略的等价物在数据访问层实现。

      3. ID 用 cuid2
         与原项目一致,主键是可排序、防碰撞的字符串 ID(cuid2),
         而非自增整数——便于分布式生成,也不在 URL 里暴露业务量。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def generate_id() -> str:
    """生成主键 ID。

    原项目用 cuid2;这里用 uuid4 的十六进制串,同样满足"唯一、不可枚举"。
    保持字符串类型以与既有数据兼容。
    """
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    """所有模型的声明式基类。"""


# ---- 常量:列长度上限,与原项目保持一致 ----
ID_LENGTH = 191
USER_ID_LENGTH = 255
VARCHAR_LENGTH = 256
FILENAME_LENGTH = 1024


class Chat(Base):
    """一场对话(聊天会话)。

    一次完整的问答历史属于一个 chat;visibility 控制是否可通过分享链接公开访问。
    """

    __tablename__ = "chats"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=generate_id)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    title: Mapped[str] = mapped_column(Text)
    user_id: Mapped[str] = mapped_column(String(USER_ID_LENGTH))
    # public=可被分享链接访问;private=仅本人
    visibility: Mapped[str] = mapped_column(String(VARCHAR_LENGTH), default="private")

    __table_args__ = (
        Index("chats_user_id_idx", "user_id"),
        Index("chats_user_id_created_at_idx", "user_id", created_at.desc()),
        Index("chats_created_at_idx", created_at.desc()),
    )


class Message(Base):
    """一条消息(用户提问或 AI 回答的"信封")。

    真正的内容在 parts 表里;这里只记角色、所属会话、时间与元数据。
    metadata 里会存 traceId、searchMode、modelId 等,供反馈与追踪关联。
    """

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=generate_id)
    chat_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("chats.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(VARCHAR_LENGTH))  # user / assistant / system
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 任意附加信息(traceId / searchMode / modelId / 反馈关联等)
    extra_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    __table_args__ = (
        Index("messages_chat_id_idx", "chat_id"),
        Index("messages_chat_id_created_at_idx", "chat_id", "created_at"),
    )


class Part(Base):
    """消息的一个内容部件(宽列设计,见文件头说明)。

    type 决定本行是哪种部件,对应一组非空列;其余类型的列留空。
    order 保证同一消息内多个部件的先后顺序(流式渲染依赖这个顺序)。
    """

    __tablename__ = "parts"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=generate_id)
    message_id: Mapped[str] = mapped_column(
        String(ID_LENGTH), ForeignKey("messages.id", ondelete="CASCADE")
    )
    order: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(VARCHAR_LENGTH))

    # 文本部件
    text_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 推理过程部件(模型思考链)
    reasoning_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 文件部件(用户上传的附件)
    file_media_type: Mapped[str | None] = mapped_column(String(VARCHAR_LENGTH), nullable=True)
    file_filename: Mapped[str | None] = mapped_column(String(FILENAME_LENGTH), nullable=True)
    file_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 来源 URL 部件(搜索结果引用)
    source_url_source_id: Mapped[str | None] = mapped_column(String(VARCHAR_LENGTH), nullable=True)
    source_url_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url_title: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 来源文档部件
    source_document_source_id: Mapped[str | None] = mapped_column(
        String(VARCHAR_LENGTH), nullable=True
    )
    source_document_media_type: Mapped[str | None] = mapped_column(
        String(VARCHAR_LENGTH), nullable=True
    )
    source_document_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_document_filename: Mapped[str | None] = mapped_column(
        String(FILENAME_LENGTH), nullable=True
    )
    source_document_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_document_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 工具调用部件(通用)
    tool_tool_call_id: Mapped[str | None] = mapped_column(String(VARCHAR_LENGTH), nullable=True)
    tool_state: Mapped[str | None] = mapped_column(String(VARCHAR_LENGTH), nullable=True)
    tool_error_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 各具体工具的输入/输出(json)
    tool_search_input: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tool_search_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tool_fetch_input: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tool_fetch_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tool_question_input: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tool_question_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tool_todo_write_input: Mapped[dict | None] = mapped_column("tool_todoWrite_input", JSON, nullable=True)
    tool_todo_write_output: Mapped[dict | None] = mapped_column("tool_todoWrite_output", JSON, nullable=True)
    tool_todo_read_input: Mapped[dict | None] = mapped_column("tool_todoRead_input", JSON, nullable=True)
    tool_todo_read_output: Mapped[dict | None] = mapped_column("tool_todoRead_output", JSON, nullable=True)

    # 动态工具(MCP 等运行时定义的工具)
    tool_dynamic_input: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tool_dynamic_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tool_dynamic_name: Mapped[str | None] = mapped_column(String(VARCHAR_LENGTH), nullable=True)
    tool_dynamic_type: Mapped[str | None] = mapped_column(String(VARCHAR_LENGTH), nullable=True)

    # 数据部件(通用 data-* part,用于 Generative UI spec 等)
    data_prefix: Mapped[str | None] = mapped_column(String(VARCHAR_LENGTH), nullable=True)
    data_content: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    data_id: Mapped[str | None] = mapped_column(String(VARCHAR_LENGTH), nullable=True)

    # 提供商元数据(如 OpenAI 的 reasoning summary 等)
    provider_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("parts_message_id_idx", "message_id"),
        Index("parts_message_id_order_idx", "message_id", "order"),
        # 与原项目一致的完整性约束:特定类型的部件必须带对应字段
        CheckConstraint("type != 'text' OR text_text IS NOT NULL", name="text_text_required"),
        CheckConstraint(
            "type != 'reasoning' OR reasoning_text IS NOT NULL", name="reasoning_text_required"
        ),
        CheckConstraint(
            "type != 'file' OR (file_media_type IS NOT NULL AND file_filename IS NOT NULL "
            "AND (file_key IS NOT NULL OR file_url IS NOT NULL))",
            name="file_fields_required",
        ),
        CheckConstraint(
            "tool_state IS NULL OR tool_state IN "
            "('input-streaming','input-available','output-available','output-error')",
            name="tool_state_valid",
        ),
    )


class Note(Base):
    """笔记。用户可从某条 AI 回答保存内容成笔记,可关联来源消息。"""

    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=generate_id)
    user_id: Mapped[str] = mapped_column(String(USER_ID_LENGTH))
    # 删除所属聊天时笔记保留(chat_id 置空),不连带删除
    chat_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("chats.id", ondelete="SET NULL"), nullable=True
    )
    source_message_id: Mapped[str | None] = mapped_column(String(ID_LENGTH), nullable=True)
    title: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("notes_user_id_idx", "user_id"),
        Index("notes_user_id_updated_at_idx", "user_id", updated_at.desc()),
        Index("notes_chat_id_idx", "chat_id"),
        Index("notes_source_message_id_idx", "source_message_id"),
    )


class LibraryFile(Base):
    """文件库。用户上传的文件元信息;实际内容存对象存储(S3),这里记 object_key。"""

    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=generate_id)
    user_id: Mapped[str] = mapped_column(String(USER_ID_LENGTH))
    chat_id: Mapped[str | None] = mapped_column(
        String(ID_LENGTH), ForeignKey("chats.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(Text)
    # 对象存储里的键(S3 object key)
    object_key: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(String(VARCHAR_LENGTH))
    size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("files_user_id_idx", "user_id"),
        Index("files_user_id_updated_at_idx", "user_id", updated_at.desc()),
        Index("files_chat_id_idx", "chat_id"),
        Index("files_media_type_idx", "media_type"),
        Index("files_object_key_idx", "object_key"),
    )


class Feedback(Base):
    """用户反馈。任何人可提交;user_id 可空(匿名反馈),用户也可事后匿名化。"""

    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(ID_LENGTH), primary_key=True, default=generate_id)
    user_id: Mapped[str | None] = mapped_column(String(USER_ID_LENGTH), nullable=True)
    sentiment: Mapped[str] = mapped_column(String(VARCHAR_LENGTH))  # positive/neutral/negative
    message: Mapped[str] = mapped_column(Text)
    page_url: Mapped[str] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("feedback_user_id_idx", "user_id"),
        Index("feedback_created_at_idx", "created_at"),
    )
