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

if FAL_KEY:
    os.environ["FAL_KEY"] = FAL_KEY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class TryOn(StatesGroup):
    waiting_person = State()
    waiting_garment_or_text = State()

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
    logger.info(f"User {message.from_user.id} started")

@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено. Напиши /start чтобы начать заново.")

@dp.message(TryOn.waiting_person, F.photo)
async def get_person(message: Message, state: FSMContext):
    try:
        await message.answer("Фото получено, обрабатываю...")
        
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        
        # Скачиваем в память, без сохранения на диск
        file_bytes = await bot.download_file(file.file_path)
        
        # Загружаем на fal
        person_url = fal_client.upload(file_bytes.read(), "image.jpg")
        
        await state.update_data(person_url=person_url)
        await state.set_state(TryOn.waiting_garment_or_text)
        
        await message.answer("Готово! Теперь пришли фото одежды или напиши текстом, во что переодеть.")
        logger.info(f"Person photo uploaded for user {message.from_user.id}")
        
    except Exception as e:
        logger.error(f"Error in get_person: {e}")
        await message.answer(f"Ошибка при обработке фото: {e}\nПопробуй ещё раз или /start")

@dp.message(TryOn.waiting_person)
async def need_photo(message: Message):
    await message.answer("Сначала пришли именно фото человека.")

@dp.message(TryOn.waiting_garment_or_text, F.photo)
async def get_garment(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        person_url = data.get("person_url")
        
        if not person_url:
            await message.answer("Что-то пошло не так. Напиши /start")
            return
            
        await message.answer("Генерирую примерку, подожди 30–70 секунд...")
        
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        file_bytes = await bot.download_file(file.file_path)
        
        garment_url = fal_client.upload(file_bytes.read(), "garment.jpg")
        
        result = fal_client.subscribe(
            "fal-ai/cat-vton",
            arguments={
                "human_image_url": person_url,
                "garment_image_url": garment_url,
                "cloth_type": "upper",
                "num_inference_steps": 30,
                "guidance_scale": 2.5,
            },
            with_logs=False,
        )
        
        result_url = result["image"]["url"]
        await message.answer_photo(result_url, caption="Готово!")
        
    except Exception as e:
        logger.error(f"Error in get_garment: {e}")
        await message.answer(f"Ошибка генерации: {e}")
    
    await state.clear()
    await message.answer("Можешь начать заново — /start")

@dp.message(TryOn.waiting_garment_or_text, F.text)
async def get_text(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        person_url = data.get("person_url")
        prompt = message.text.strip()
        
        if not person_url:
            await message.answer("Что-то пошло не так. Напиши /start")
            return
            
        if len(prompt) < 2:
            await message.answer("Напиши более подробное описание.")
            return
            
        await message.answer("Меняю одежду, подожди...")
        
        full_prompt = (
            f"Change the clothing of the person to: {prompt}. "
            "Keep the same face, body, pose, background and lighting. "
            "Photorealistic, high quality."
        )
        
        result = fal_client.subscribe(
            "fal-ai/flux/dev",
            arguments={
                "prompt": full_prompt,
                "image_url": person_url,
                "strength": 0.7,
                "num_inference_steps": 28,
                "guidance_scale": 3.5,
            },
            with_logs=False,
        )
        
        result_url = result["images"][0]["url"]
        await message.answer_photo(result_url, caption=f"Готово!\nЗапрос: {prompt}")
        
    except Exception as e:
        logger.error(f"Error in get_text: {e}")
        await message.answer(f"Ошибка: {e}")
    
    await state.clear()
    await message.answer("Можешь начать заново — /start")

@dp.message(TryOn.waiting_garment_or_text)
async def need_garment_or_text(message: Message):
    await message.answer("Пришли фото одежды или текст.")

async def main():
    logger.info("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
