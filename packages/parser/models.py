from pydantic import BaseModel


class Position(BaseModel):
    title: str
    company: str
    start_date: str
    end_date: str
    is_current: bool


class Education(BaseModel):
    degree: str
    institution: str
    graduation_date: str


class Resume(BaseModel):
    name: str
    email: str
    phone: str
    location: str
    positions: list[Position]
    education: list[Education]
    skills: list[str]
