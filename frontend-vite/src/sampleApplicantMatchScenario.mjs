export const SAMPLE_JOB_DESCRIPTION = `# Python Backend Engineer — Sample Test Role

Location: Hyderabad, India (Hybrid)
Employment: Full-time
Experience: 3–5 years

## Role overview
Build and maintain reliable APIs and backend services for a recruitment technology platform. Work with product and frontend engineers to design clear API contracts, improve data access performance, write maintainable code, and support production releases.

## Responsibilities
- Design, build, document and maintain REST APIs using Python and FastAPI.
- Implement request validation, authentication, authorization and consistent error handling.
- Build data models and efficient queries using PostgreSQL and SQLAlchemy or an equivalent ORM.
- Write unit and integration tests and participate in code reviews.
- Improve API latency, reliability and observability; investigate production issues.
- Use asynchronous programming where it provides a measurable benefit.
- Package services with Docker and contribute to CI/CD pipelines.
- Collaborate with frontend, QA and product teammates; communicate trade-offs and delivery risks clearly.

## Required qualifications
- 3+ years of professional backend development experience.
- Strong Python fundamentals and experience building production backend services.
- Hands-on experience with FastAPI, Flask, Django REST Framework or a comparable API framework; FastAPI is preferred.
- Practical SQL and PostgreSQL experience, including schema design, joins, indexes and query optimisation.
- Experience designing REST APIs, request validation and robust error handling.
- Automated testing experience using pytest or an equivalent framework.
- Familiarity with authentication and API security fundamentals (JWT, role-based access, input validation and safe handling of secrets).
- Experience with Git and collaborative development practices.

## Preferred qualifications
- Async Python, background jobs, queues, caching or Redis.
- Docker and a cloud platform such as AWS, Azure or GCP.
- CI/CD using GitHub Actions or a comparable tool.
- Monitoring, structured logging and performance profiling.
- Experience supporting a product with measurable availability or latency requirements.

Fair evaluation: assess only job-related evidence. Missing resume evidence means not demonstrated, not proof that the candidate lacks the skill. `;

export const SAMPLE_RESUME_TEXT = `AARAV SHARMA
PYTHON BACKEND ENGINEER | SAMPLE TEST CANDIDATE
Hyderabad, India | aarav.sharma@example.invalid | Portfolio: example.invalid/aarav

PROFESSIONAL SUMMARY
Python backend engineer with approximately 4 years of professional experience building API-driven web applications. Hands-on with Python, FastAPI, PostgreSQL, SQLAlchemy, pytest, Docker and GitHub Actions. Experienced in API validation, authentication, database query tuning and collaborating with frontend and QA teams. Interested in reliable, maintainable backend systems and measurable performance improvements.

TECHNICAL SKILLS
Languages: Python, SQL, basic JavaScript
Backend: FastAPI, Flask, REST APIs, Pydantic, SQLAlchemy, async/await
Data: PostgreSQL, relational modelling, indexes, migrations, Redis (working familiarity)
Quality & Security: pytest, unit/integration testing, JWT, role-based access control, input validation
Delivery & Tools: Docker, Git, GitHub Actions, Linux, basic AWS deployment, structured logging

PROFESSIONAL EXPERIENCE
Software Engineer | Northstar Digital Labs (fictional) | Hyderabad | Jan 2023 - Present
Developed and maintained Python/FastAPI services for an internal operations platform, implementing REST endpoints, Pydantic request validation, OpenAPI documentation and consistent exception responses.
Worked with PostgreSQL and SQLAlchemy to design relational models, write joins, add indexes, manage schema migrations and tune frequently used queries.
Added JWT-based authentication and role checks to protected endpoints; moved secrets into environment-based configuration and strengthened input validation.
Created pytest unit and integration tests for API routes and service logic; connected the test suite to GitHub Actions so pull requests ran automated checks.
Containerised services with Docker and supported application releases through a documented CI workflow; investigated logs and production defects with senior engineers.
Used async endpoints for selected I/O-bound operations. In a fictional internal test scenario, query and endpoint improvements reduced a representative endpoint's p95 response time from about 820 ms to 470 ms.

Junior Python Developer | ByteTrail Labs (fictional) | Hyderabad | Jun 2022 - Dec 2022
Implemented Python utilities and Flask API changes, fixed defects, wrote SQL queries and assisted with integration testing and code reviews.
Worked with Git-based team workflows and prepared short technical notes for features and bug fixes.

SELECTED PROJECT
Recruitment Operations API (sample project)
Designed sample endpoints for job records, candidate profiles and application status using FastAPI, Pydantic, SQLAlchemy and PostgreSQL.
Added role-aware access checks, input validation, pytest coverage for core workflows and Docker-based local development.
Documented API contracts and used GitHub Actions to run linting and tests on proposed changes.

EDUCATION
Bachelor of Technology (B.Tech), Computer Science | Deccan Institute of Technology (fictional) | 2018 - 2022

ADDITIONAL INFORMATION
Availability: 30 days (sample) | Work preference: Hyderabad hybrid | Languages: English, Hindi, Telugu`;

export const SAMPLE_MANUAL_REFERENCE = Object.freeze({
  score: 75,
  label: "Manual benchmark only",
  note: "Independently scored on a separate 10-criterion rubric. It is a qualitative comparison point, not the expected numeric output of BluePace's configured scoring weights.",
});
