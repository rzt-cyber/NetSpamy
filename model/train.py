import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification, Trainer, TrainingArguments
from sklearn.model_selection import train_test_split
import pandas as pd
from torch.utils.data import Dataset

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

# Загрузка данных
df = pd.read_csv("./model/data/dataset.xls")
texts = df["text"].tolist()
labels = df["label"].tolist()

tokenizer = AutoTokenizer.from_pretrained("cointegrated/rubert-tiny")
model = AutoModelForSequenceClassification.from_pretrained("cointegrated/rubert-tiny", num_labels=2)

# Разделение на обучающую и валидационную выборки
train_texts, val_texts, train_labels, val_labels = train_test_split(texts, labels, test_size=0.2)
train_dataset = ToxicDataset(train_texts, train_labels, tokenizer)
val_dataset = ToxicDataset(val_texts, val_labels, tokenizer)

# Параметры обучения
training_args = TrainingArguments(
    output_dir="./model/my_model",
    per_device_train_batch_size=8,
    per_device_eval_batch_size=8,
    num_train_epochs=3,
    eval_strategy="epoch",
    save_strategy="epoch",
    logging_dir="./logs",
    logging_steps=10,
    load_best_model_at_end=True,
)

# Trainer
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=val_dataset,
    tokenizer=tokenizer
)

# Обучение
trainer.train()

# Сохранение
model.save_pretrained("./model/my_model")
tokenizer.save_pretrained("./model/my_model")