import asyncio
import json
import re
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, WebSocket
from parser import get_page
from starlette.concurrency import run_in_threadpool
from sqlmodel import Field, SQLModel, create_engine, Session, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.websockets import WebSocketDisconnect


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("lifespan start")
    create_db_and_tables()
    await startup_event()
    yield
    print("lifespan end")


app = FastAPI(lifespan=lifespan)


async def startup_event():
    asyncio.create_task(background_parser_async())


# Класс для управления подключениями веб-сокетов
class ConnectionManager:

    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.connections.remove(websocket)

    async def broadcast(self, data: str):
        for connection in self.connections:
            await connection.send_text(data)


manager = ConnectionManager()


# Модель данных для хранения товаров в базе данных
class Prices(SQLModel, table=True):
    id: int = Field(primary_key=True)
    name: str
    cost: int


sqlite_url = "sqlite:///parser.db"
engine = create_engine(sqlite_url)


def get_async_session():
    sqlite_url_2 = "sqlite+aiosqlite:///parser.db"
    engine_2 = create_async_engine(sqlite_url_2)
    dbsession = async_sessionmaker(engine_2)
    return dbsession()


async def get_session():
    async with get_async_session() as session:
        yield session


SessionDep = Depends(get_session)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def add_item(session: Session, title: str, price: int):
    existing_item = session.exec(select(Prices).where(Prices.name == title)).first()
    if not existing_item:
        new_item = Prices(name=title, cost=price)
        session.add(new_item)
        session.commit()
        session.refresh(new_item)
        print(f"Added to DB: {new_item}")
    else:
        print(f"Item: {existing_item}")


def clean_price(price_str: str) -> int:
    cleaned_price = re.sub(r"\D", "", price_str)
    return int(cleaned_price)


async def background_parser_async():
    while True:
        print("Starting get price")
        items = await run_in_threadpool(get_page)
        with Session(engine) as session:
            for item in items:
                try:
                    price = clean_price(item["price"])
                    new_item = add_item(session, title=item["title"], price=price)
                    if new_item:
                        await manager.broadcast(new_item.model_dump_json())
                except ValueError as e:
                    print(f"Error processing item: {item}. Error: {e}")
        print("Database updated!")
        await asyncio.sleep(12 * 60 * 60)


@app.get("/prices")
async def read_prices(session: Session = SessionDep, offset: int = 0, limit: int = 100):
    stmt = select(Prices).offset(offset).limit(limit)
    items = await session.scalars(stmt)
    [await manager.broadcast(item.model_dump_json()) for item in items]
    return items.all()


@app.get("/prices/{item_id}")
async def read_item(item_id: int, session: Session = SessionDep):
    price = await session.get(Prices, item_id)
    if not price:
        raise HTTPException(status_code=404, detail="Price not found")
    await manager.broadcast(price.model_dump_json())
    return price


@app.put("/prices/{item_id}")
async def update_item(item_id: int, data: Prices, session: Session = SessionDep):
    price_db = await session.get(Prices, item_id)
    if not price_db:
        raise HTTPException(status_code=404, detail="Price not found")
    price_data = data.model_dump(exclude_unset=True)
    price_db.sqlmodel_update(price_data)
    session.add(price_db)
    await session.commit()
    session.refresh(price_db)
    await manager.broadcast(json.dumps({"action": "update", "id": item_id}))
    return price_db


@app.post("/prices/create")
async def create_item(item: Prices, session: Session = SessionDep):
    session.add(item)
    await session.commit()
    await session.refresh(item)
    await manager.broadcast(item.model_dump_json())
    return item


@app.delete("/prices/{item_id}")
async def delete_item(item_id: int, session: Session = SessionDep):
    price = await session.get(Prices, item_id)
    if not price:
        raise HTTPException(status_code=404, detail="Price not found")
    await session.delete(price)
    await session.commit()
    await manager.broadcast(json.dumps({"action": "delete", "id": item_id}))
    return {"ok": True}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print(f"Client {websocket} disconnected")
