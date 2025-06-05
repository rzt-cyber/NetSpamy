import os
import pandas as pd
import torch
from torch.utils.data import Dataset
from sklearn.model_selection import train_test_split
from transformers import AutoTokenizer, AutoModelForSequenceClassification, Trainer, TrainingArguments

# Список моделей
MODELS = {
    "ai-forever": "ai-forever/ruBert-base",
    "sberbank-ai": "sberbank-ai/ruBert-large"
}

# Загрузка датасета
df = pd.read_csv("model/data/filename.xls")
texts = df["text"].tolist()
labels = df["label"].tolist()

train_texts, val_texts, train_labels, val_labels = train_test_split(
    texts, labels, test_size=0.2, random_state=42, stratify=labels
)

# Кастомный Dataset
class ToxicDataset(Dataset):
    def __init__(self, texts, labels, tokenizer, max_len=128):
        self.texts = texts
        self.labels = labels
        self.tokenizer = tokenizer
        self.max_len = max_len

    def __getitem__(self, idx):
        encoding = self.tokenizer(
            self.texts[idx],
            truncation=True,
            padding="max_length",
            max_length=self.max_len,
            return_tensors="pt"
        )
        return {
            "input_ids": encoding["input_ids"].squeeze(),
            "attention_mask": encoding["attention_mask"].squeeze(),
            "labels": torch.tensor(self.labels[idx])
        }

    def __len__(self):
        return len(self.texts)

# Цикл по моделям
for name, model_id in MODELS.items():
    print(f"\n Обучаем модель: {name}")

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForSequenceClassification.from_pretrained(model_id, num_labels=2)

    train_dataset = ToxicDataset(train_texts, train_labels, tokenizer)
    val_dataset = ToxicDataset(val_texts, val_labels, tokenizer)

    output_dir = f"./trained_models/{name}"
    os.makedirs(output_dir, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=3,
        per_device_train_batch_size=8,
        per_device_eval_batch_size=8,
        eval_strategy="epoch",
        save_strategy="epoch",
        logging_dir=f"{output_dir}/logs",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss"
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        tokenizer=tokenizer
    )

    trainer.train()
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)

    print(f" Модель {name} сохранена в {output_dir}")
