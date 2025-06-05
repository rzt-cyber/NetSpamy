import pandas as pd
import torch
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import matplotlib.pyplot as plt


# Фиксируем random_state
RANDOM_STATE = 42

# 🔧 Модели
MODELS = {
    "sberbank-ai": "./model/model"
}

# Загрузка модели и токенизатора
def load_model(model_id):
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForSequenceClassification.from_pretrained(model_id, num_labels=2)
    model.eval()
    return tokenizer, model

# Предсказание
def predict(texts, tokenizer, model):
    preds = []
    for text in texts:
        tokens = tokenizer(text, return_tensors="pt", truncation=True, padding=True, max_length=128)
        with torch.no_grad():
            outputs = model(**tokens)
        probs = torch.softmax(outputs.logits, dim=1)
        toxic_score = probs[0][1].item() if probs.shape[1] >= 2 else 0
        preds.append(1 if toxic_score > 0.5 else 0)
    return preds

# Загрузка датасета
df = pd.read_csv("model/data/messages_test.xls")
texts = df["text"].tolist()
labels = df["label"].tolist()

texts_train = texts
labels_train = labels

# Метрики
results = {}

for name, model_id in MODELS.items():
    print(f"\n🔍 Модель: {name}")
    tokenizer, model = load_model(model_id)
    preds = predict(texts_train, tokenizer, model)

    acc = accuracy_score(labels_train, preds)
    prec = precision_score(labels_train, preds, zero_division=0)
    rec = recall_score(labels_train, preds, zero_division=0)
    f1 = f1_score(labels_train, preds, zero_division=0)

    results[name] = {
        "accuracy": acc,
        "precision": prec,
        "recall": rec,
        "f1": f1
    }

# Вывод в консоль
print("\n📊 Метрики:")
for model_name, metrics in results.items():
    print(f"\n📌 {model_name}")
    for m, v in metrics.items():
        print(f"{m.capitalize()}: {v:.4f}")

# График
labels_plt = list(results.keys())
f1s = [results[m]["f1"] for m in labels_plt]

plt.figure(figsize=(8, 5))
plt.bar(labels_plt, f1s, color="skyblue")
plt.title("F1-метрика по моделям")
plt.ylabel("F1-score")
plt.ylim(0, 1)
plt.grid(True, linestyle="--", alpha=0.5)
plt.tight_layout()
plt.show()
