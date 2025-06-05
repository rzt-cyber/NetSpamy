import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification, Trainer, TrainingArguments
from sklearn.model_selection import train_test_split
import pandas as pd
from torch.utils.data import Dataset
import re
import random
import nlpaug.augmenter.word as naw

# Очистка текста
def clean_text(text):
    text = text.lower()
    text = re.sub(r"http\S+|www\S+|https\S+", "", text)
    text = re.sub(r"@\w+|#\w+", "", text)
    text = re.sub(r"[^\w\s!?.,]", "", text, flags=re.UNICODE)
    text = " ".join(text.split())
    return text

# Кастомный Dataset с опциональной аугментацией
class ToxicDataset(Dataset):
    def __init__(self, texts, labels, tokenizer, max_len=128, augment=False, aug_prob=0.5):
        self.tokenizer = tokenizer
        self.max_len = max_len
        self.labels = labels
        self.augment = augment
        self.aug_prob = aug_prob
        self.syn_aug = naw.SynonymAug(aug_src='wordnet')
        self.texts = [clean_text(t) for t in texts]

    def __getitem__(self, idx):
        text = self.texts[idx]
        # Аугментация: случайно применяем к части примеров
        if self.augment and random.random() < self.aug_prob:
            try:
                text = self.syn_aug.augment(text)
            except Exception:
                pass  # на всякий случай, если аугментатор не справится

        encoding = self.tokenizer(
            text,
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
df = pd.read_csv("data/filename.xls")
texts = df["text"].tolist()
labels = df["label"].tolist()

# Токенизатор и модель
tokenizer = AutoTokenizer.from_pretrained("sberbank-ai/ruBert-large")
model = AutoModelForSequenceClassification.from_pretrained("sberbank-ai/ruBert-large", num_labels=2)

# Разделение
train_texts, val_texts, train_labels, val_labels = train_test_split(
    texts, labels, test_size=0.2, random_state=42, stratify=labels
)

# Датасеты
train_dataset = ToxicDataset(train_texts, train_labels, tokenizer, augment=True, aug_prob=0.5)
val_dataset = ToxicDataset(val_texts, val_labels, tokenizer, augment=False)

# Параметры обучения
training_args = TrainingArguments(
    output_dir="./model",
    per_device_train_batch_size=8,
    per_device_eval_batch_size=8,
    num_train_epochs=3,
    eval_strategy="epoch",
    save_strategy="epoch",
    logging_dir="./logs",
    logging_steps=10,
    load_best_model_at_end=True,
)

# Обучение
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=val_dataset,
    tokenizer=tokenizer
)

trainer.train()

# Сохраняем
model.save_pretrained("./model")
tokenizer.save_pretrained("./model")