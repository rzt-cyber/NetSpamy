from model.predict import predict_toxicity

def check_message(text):
    result = predict_toxicity(text)
    return {
        "is_toxic": result == 1,
        "label": result
    }