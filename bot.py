import os
import asyncio
import logging
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

import fal_client

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
FAL_KEY = os.getenv("FAL_KEY")

os.environ["FAL_KEY"] = FAL_KEY

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class TryOn(StatesGroup):
    waiting_person = State()
    waiting_garment_or_text = State()

async def download_photo(message: Message, bot: Bot) -> str:
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    file_path = f"temp_{message.from_user.id}_{photo.file_id}.jpg"
    await bot.download_file(file.file_path, file_path)
    return file_path

async def upload_to_fal(path: str) -> str:
    url = fal_client.upload_file(path)
    return url

async def run_catvton(person_url: str, garment_url: str, cloth_type: str = "upper"):
    result = fal_client.subscribe(
        "fal-ai/cat-vton",
        arguments={
            "human_image_url": person_url,
            "garment_image_url": garment_url,
            "cloth_type": cloth_type,
            "num_inference_steps": 30,
            "guidance_scale": 2.5,
        },
        with_logs=False,
    )
    return result["image"]["url"]

async def run_text_change(person_url: str, prompt: str):
    full_prompt = (
        f"Change the clothing of the person to: {prompt}. "
        "Keep the same face, body, pose, background and lighting. "
        "Photorealistic, high quality, detailed clothes."
    )
    result = fal_client.subscribe(
        "fal-ai/flux/dev",
        arguments={
            "prompt": full_prompt,
            "image_url": person_url,
            "strength": 0.75,
            "num_inference_steps": 28,
            "guidance_scale": 3.5,
        },
        with_logs=False,
    )
    return result["images"][0]["url"]

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Я бот для смены одежды.\n\n"
        "Как пользоваться:\n"
        "1. Отправь фото человека\n"
        "2. Потом отправь либо:\n"
        "   • фото одежды — для точной примерки\n"
        "   • или текст (например: «красное платье»)\n\n"
        "Команды:\n"
        "/start — начать заново\n"
        "/cancel — отменить"
    )
    await state.set_state(TryOn.waiting_person)

@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено. Напиши /start чтобы начать заново.")

@dp.message(TryOn.waiting_person, F.photo)
async def get_person(message: Message, state: FSMContext, bot: Bot):
    await message.answer("Фото человека получено. Теперь пришли фото одежды или напиши текстом, во что переодеть.")
    path = await download_photo(message, bot)
    person_url = await upload_to_fal(path)
    try:
        os.remove(path)
    except:
        pass
    await state.update_data(person_url=person_url)
    await state.set_state(TryOn.waiting_garment_or_text)

@dp.message(TryOn.waiting_person)
async def need_photo(message: Message):
    await message.answer("Сначала пришли фото человека.")

@dp.message(TryOn.waiting_garment_or_text, F.photo)
async def get_garment(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    person_url = data.get("person_url")
    await message.answer("Генерирую примерку, подожди 20–60 секунд...")
    path = await download_photo(message, bot)
    garment_url = await upload_to_fal(path)
    try:
        os.remove(path)
    except:
        pass
    try:
        result_url = await run_catvton(person_url, garment_url, cloth_type="upper")
        await message.answer_photo(result_url, caption="Готово!")
    except Exception as e:
        await message.answer(f"Ошибка генерации: {e}")
    await state.clear()
    await message.answer("Можешь начать заново — пришли новое фото или /start")

@dp.message(TryOn.waiting_garment_or_text, F.text)
async def get_text(message: Message, state: FSMContext):
    data = await state.get_data()
    person_url = data.get("person_url")
    prompt = message.text.strip()
    if len(prompt) < 2:
        await message.answer("Напиши более подробное описание одежды.")
        return
    await message.answer("Меняю одежду по описанию, подожди...")
    try:
        result_url = await run_text_change(person_url, prompt)
        await message.answer_photo(result_url, caption=f"Готово!\nЗапрос: {prompt}")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
    await state.clear()
    await message.answer("Можешь начать заново — пришли новое фото или /start")

@dp.message(TryOn.waiting_garment_or_text)
async def need_garment_or_text(message: Message):
    await message.answer("Пришли фото одежды или напиши текстом, во что переодеть человека.")

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
