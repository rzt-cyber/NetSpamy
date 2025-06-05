from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
import re

#  Функция очистки текста
def clean_text(text):
    text = text.lower()  # Приводим к нижнему регистру
    text = re.sub(r"http\S+|www\S+|https\S+", "", text)  # Удаляем ссылки
    text = re.sub(r"@\w+|#\w+", "", text)  # Удаляем упоминания и хэштеги
    text = re.sub(r"[^\w\s!?.,]", "", text, flags=re.UNICODE)  # Удаляем спецсимволы
    text = " ".join(text.split())  # Удаляем лишние пробелы
    return text

# Загрузка модели
model_name = "sberbank-ai/ruBert-large"  # базовая модель
model = AutoModelForSequenceClassification.from_pretrained("./model/model")  # дообученная
tokenizer = AutoTokenizer.from_pretrained(model_name)
model.eval()

# Предсказание
def predict_toxicity(text):
    cleaned_text = clean_text(text)  # Очищаем входной текст
    tokens = tokenizer(cleaned_text, return_tensors="pt", truncation=True, padding=True, max_length=128)
    with torch.no_grad():
        outputs = model(**tokens)
    logits = outputs.logits
    predicted_class = torch.argmax(logits, dim=1).item()
    return predicted_class
