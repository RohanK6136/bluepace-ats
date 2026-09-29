from pydantic import BaseModel, Field
from typing import List, Optional

class Experience(BaseModel):
    company: Optional[str] = None
    title: Optional[str] = None
    duration: Optional[str] = None
    description: Optional[str] = None

class Education(BaseModel):
    degree: Optional[str] = None
    university: Optional[str] = None
    cgpa: Optional[str] = None
    graduation_year: Optional[str] = None

class ResumeData(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    skills: List[str] = []
    experience: List[Experience] = []
    education: List[Education] = []
    hobbies: List[str] = []
    university_projects: List[str] = []
    highest_education: Optional[str] = None
    is_fresher: bool = False
    raw_text_length: int = 0