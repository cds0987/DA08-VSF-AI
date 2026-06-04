from pydantic import BaseModel


class ByDayMetric(BaseModel):
    date: str
    count: int


class FeedbackMetric(BaseModel):
    up: int
    down: int
    rate: float


class TopQuestionMetric(BaseModel):
    question: str
    count: int


class AdminMetrics(BaseModel):
    total_questions: int
    by_day: list[ByDayMetric]
    feedback: FeedbackMetric
    top_questions: list[TopQuestionMetric]
