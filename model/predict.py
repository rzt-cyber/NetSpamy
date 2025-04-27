from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

# Загрузка модели
model_name = "cointegrated/rubert-tiny"  # предобученная модель
model = AutoModelForSequenceClassification.from_pretrained("./model/my_model")  # тут лежит своя
tokenizer = AutoTokenizer.from_pretrained(model_name)
model.eval()

def predict_toxicity(text):
    tokens = tokenizer(text, return_tensors="pt", truncation=True, padding=True, max_length=128)
    with torch.no_grad():
        outputs = model(**tokens)
    logits = outputs.logits
    predicted_class = torch.argmax(logits, dim=1).item()
    return predicted_class
