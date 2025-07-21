# **6\. 代码目录结构 (Source Tree)**

系统采用单体仓库（Monorepo）结构进行管理：

Plaintext

ipc-project/
├── .github/
│   └── workflows/
│       └── ci.yaml
├── docs/
│   ├── prd.md
│   └── architecture.md
├── packages/
│   ├── ipc\_client\_sdk/
│   │   ├── ipc\_client\_sdk/
│   │   ├── tests/
│   │   └── pyproject.toml
│   ├── ipc\_router/
│   │   ├── ipc\_router/
│   │   │   ├── api/
│   │   │   ├── application/
│   │   │   ├── domain/
│   │   │   └── infrastructure/
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   └── ipc\_cli/
│       ├── ipc\_cli/
│       ├── tests/
│       └── pyproject.toml
├── docker-compose.yaml
├── pyproject.toml
└── README.md
