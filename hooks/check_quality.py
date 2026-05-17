#!/usr/bin/env python3
"""Quality scoring for knowledge entry JSON files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DimensionScore:
    name: str
    score: float
    max_score: float
    feedback: list[str] = field(default_factory=list)

    @property
    def percentage(self) -> float:
        if self.max_score == 0:
            return 0.0
        return (self.score / self.max_score) * 100


@dataclass
class QualityReport:
    file_path: Path
    dimensions: list[DimensionScore] = field(default_factory=list)
    total_score: float = 0.0
    max_total: float = 100.0
    grade: str = "C"

    @property
    def percentage(self) -> float:
        if self.max_total == 0:
            return 0.0
        return (self.total_score / self.max_total) * 100


TECH_KEYWORDS = {
    "算法", "模型", "架构", "框架", "API", "分布式", "并发", "数据库",
    "缓存", "微服务", "容器", "kubernetes", "docker", "机器学习", "深度学习",
    "神经网络", "transformer", "llm", "大模型", "向量", "检索", "索引",
    "优化", "性能", "安全", "加密", "协议", "编译器", "运行时", "异步",
    "函数式", "面向对象", "响应式", "事件驱动", "流式", "批处理", "实时",
    "量子", "区块链", "物联网", "边缘计算", "云原生", "devops", "ci/cd",
    "测试", "监控", "日志", "追踪", "网关", "负载均衡", "高可用", "容错",
    "一致性", "事务", "锁", "队列", "管道", "过滤", "聚合", "分片",
    "集群", "节点", "副本", "备份", "恢复", "迁移", "升级", "降级",
    "节流", "熔断", "降级", "限流", "重试", "超时", "幂等", "去重",
    "序列化", "反序列化", "编码", "解码", "压缩", "解压", "加密", "解密",
    "认证", "授权", "审计", "合规", "隐私", "脱敏", "水印", "签名",
    "哈希", "校验", "验证", "证明", "共识", "投票", "选举", "复制",
    "同步", "异步", "阻塞", "非阻塞", "回调", "协程", "纤程", "线程",
    "进程", "内存", "磁盘", "网络", "文件系统", "内核", "驱动", "固件",
    "硬件", "虚拟化", "仿真", "模拟", "渲染", "计算", "存储", "传输",
    "带宽", "延迟", "吞吐量", "qps", "tps", "rps", "并发数", "连接数",
    "cpu", "gpu", "tpu", "npu", "fpga", "asic", "内存", "显存",
    "磁盘", "ssd", "hdd", "nvme", "raid", "san", "nas", "对象存储",
    "块存储", "文件存储", "数据仓库", "数据湖", "数据中台", "数据治理",
    "etl", "elt", "数据流", "数据管道", "数据质量", "元数据", "主数据",
    "特征工程", "模型训练", "推理", "部署", "服务化", "量化", "剪枝",
    "蒸馏", "联邦学习", "迁移学习", "强化学习", "监督学习", "无监督学习",
    "半监督学习", "自监督学习", "对比学习", "生成式", "判别式", "编码器",
    "解码器", "注意力", "多头", "位置编码", "嵌入", "token", "prompt",
    "微调", "预训练", "对齐", "rlhf", "dpo", "sft", "peft", "lora",
    "qlora", "adapter", "prefix", "p-tuning", "知识图谱", "语义", "本体",
    "推理", "演绎", "归纳", "因果", "相关", "回归", "分类", "聚类",
    "降维", "异常检测", "推荐", "排序", "匹配", "相似度", "距离",
    "向量检索", "近似最近邻", "ann", "hnsw", "ivf", "pq", "sq",
    "量化", "乘积量化", "标量量化", "二值化", "哈希", "局部敏感哈希",
    "图算法", "最短路径", "最小生成树", "拓扑排序", "强连通", "社区发现",
    "中心性", "pagerank", "randomwalk", "图神经网络", "gnn", "gat", "gcn",
    "消息传递", "图注意力", "图卷积", "图嵌入", "知识蒸馏", "模型压缩",
    "稀疏化", "结构化", "非结构化", "动态图", "静态图", "异构图", "超图",
    "时间序列", "预测", "异常", "趋势", "季节性", "周期性", "平稳性",
    "自相关", "偏相关", "arima", "prophet", "状态空间", "卡尔曼滤波",
    "粒子滤波", "隐马尔可夫", "hmm", "crf", "条件随机场", "随机场",
    "马尔可夫", "贝叶斯", "概率图", "因子图", "变分推断", "采样",
    "mcmc", "蒙特卡洛", "吉布斯", "metropolis", "重要性采样", "拒绝采样",
    "生成模型", "vae", "gan", "diffusion", "flow", "energy", "score",
    "normalizing", "自回归", "自编码器", "玻尔兹曼机", "受限玻尔兹曼机",
    "信念网络", "神经辐射场", "nerf", "3d", "点云", "网格", "体素",
    "渲染", "光线追踪", "光栅化", "纹理", "材质", "着色器", "后处理",
    "计算机视觉", "图像", "视频", "音频", "语音", "文本", "多模态",
    "跨模态", "模态融合", "模态对齐", "模态转换", "模态翻译", "模态检索",
    "目标检测", "分割", "实例分割", "语义分割", "全景分割", "关键点",
    "姿态估计", "人脸识别", "文字识别", "ocr", "目标跟踪", "动作识别",
    "视频理解", "视频生成", "图像生成", "图像编辑", "图像修复", "超分辨率",
    "风格迁移", "图像翻译", "域适应", "域泛化", "零样本", "少样本",
    "元学习", "学习学习", "maml", "原型网络", "关系网络", "匹配网络",
    "记忆网络", "神经图灵机", "可微分计算机", "注意力机制", "自注意力",
    "多头注意力", "交叉注意力", "稀疏注意力", "线性注意力", "局部注意力",
    "全局注意力", "相对位置", "绝对位置", "旋转位置", "rope", "alibi",
    "前缀注意力", "滑动窗口", " dilated", "膨胀", "空洞", "分离", "解耦",
    "蒸馏", "压缩", "加速", "优化", "编译", "解释", "jit", "aot",
    "静态分析", "动态分析", "符号执行", "模糊测试", "污点分析", "数据流",
    "控制流", "依赖分析", "指针分析", "逃逸分析", "别名分析", " shape",
    "类型推断", "类型检查", "类型转换", "泛型", "协变", "逆变", "不变",
    "高阶", "高阶函数", "闭包", "lambda", "匿名函数", "柯里化", "组合子",
    "单子", "函子", "应用函子", "幺半群", "半群", "格", "偏序", "全序",
    "等价", "同构", "同态", "同余", "商", "积", "和", "指数",
    "自然变换", "伴随", "极限", "余极限", "始对象", "终对象", "零对象",
    "kernel", "cokernel", "image", "coimage", " exact", "正合", "短正合",
    "长正合", "导出函子", "tor", "ext", "上同调", "同调", "谱序列",
    "层", "束", "向量丛", "主丛", "联络", "曲率", "示性类", "指标定理",
}

STANDARD_TAGS = {
    "agent", "tool-use", "code-generation", "llm", "framework", "library",
    "tutorial", "paper", "research", "infrastructure", "devops", "security",
    "performance", "database", "frontend", "backend", "fullstack", "mobile",
    "cloud", "ai", "ml", "nlp", "cv", "robotics", "blockchain", "web3",
    "opensource", "api", "sdk", "cli", "gui", "testing", "monitoring",
    "logging", "caching", "message-queue", "stream-processing", "batch-processing",
    "data-engineering", "data-science", "analytics", "visualization", "etl",
    "kubernetes", "docker", "serverless", "microservices", "monolith",
    "graphql", "rest", "websocket", "grpc", "protocol", "standard",
    "compiler", "interpreter", "vm", "runtime", "language", "syntax",
    "type-system", "memory-management", "concurrency", "parallelism",
    "distributed-systems", "consensus", "replication", "sharding",
    "load-balancing", "circuit-breaker", "rate-limiting", "retry",
    "observability", "tracing", "metrics", "alerting", "incident-response",
    "chaos-engineering", "sre", "platform-engineering", "gitops",
    "iac", "terraform", "ansible", "puppet", "chef", "vagrant",
    "ci-cd", "github-actions", "gitlab-ci", "jenkins", "circleci",
    "travis", "argo", "flux", "spinnaker", "tekton", "buildkite",
    "npm", "yarn", "pnpm", "pip", "conda", "maven", "gradle", "cargo",
    "go-modules", "composer", "bundler", "gems", "cocoapods", "swiftpm",
    "nuget", "chocolatey", "homebrew", "apt", "yum", "dnf", "pacman",
    "docker-hub", "quay", "harbor", "ecr", "acr", "gcr", "artifact-registry",
    "helm", "kustomize", "operator", "crd", "admission-controller",
    "service-mesh", "istio", "linkerd", "consul", "envoy", "traefik",
    "nginx", "apache", "haproxy", "varnish", "squid", "cdn", "waf",
    "ddos", "bot-detection", "captcha", "oauth", "oidc", "saml", "ldap",
    "sso", "mfa", "rbac", "abac", "policy", "audit", "compliance",
    "gdpr", "ccpa", "hipaa", "soc2", "iso27001", "pci-dss", "fedramp",
    "zero-trust", "beyondcorp", "vpn", "wireguard", "openvpn", "ipsec",
    "tls", "mtls", "certificate", "pki", "hsm", "kms", "secrets",
    "vault", "sops", "sealed-secrets", "external-secrets", "cert-manager",
    "letsencrypt", "acme", "dns", "bind", "powerdns", "coredns", "route53",
    "cloudflare", "akamai", "fastly", "cloudfront", "akamai", "limelight",
    "edge-computing", "fog-computing", "iot", "mqtt", "coap", "lwm2m",
    "opc-ua", "modbus", "bacnet", "zigbee", "z-wave", "ble", "lora",
    "nb-iot", "5g", "wifi", "bluetooth", "nfc", "rfid", "gps", "gnss",
    "rtk", "ins", "slam", "localization", "mapping", "navigation",
    "planning", "control", "perception", "prediction", "fusion",
    "sensor", "camera", "lidar", "radar", "ultrasonic", "imu", "gps",
    "encoder", "odometer", "tachometer", "flow-meter", "thermometer",
    "barometer", "hygrometer", "anemometer", "pyranometer", "pyrheliometer",
    "radiometer", "spectrometer", "interferometer", "polarimeter",
    "refractometer", "densitometer", "viscometer", "rheometer",
    "tensiometer", "porosimeter", "permeameter", "calorimeter",
    "bomb-calorimeter", "dsc", "tga", "dta", "dma", "tma", "rheology",
    "rheometer", "viscometer", "texture-analyzer", "hardness-tester",
    "tensile-tester", "compression-tester", "flexural-tester", "impact-tester",
    "fatigue-tester", "creep-tester", "stress-relaxation-tester", "fracture-tester",
    "wear-tester", "friction-tester", "scratch-tester", "indentation-tester",
    "nanoindentation", "afm", "sem", "tem", "fib", "fib-sem", "stem",
    "eels", "edx", "wdx", "ebsd", "cl", "cathodoluminescence", "ebic",
    "ebeam", "ion-beam", "laser", "xray", "neutron", "electron",
    "positron", "muon", "proton", "ion", "photon", "phonon", "magnon",
    "plasmon", "polariton", "exciton", "biexciton", "trion", "charge-density-wave",
    "spin-density-wave", "superconductivity", "superfluidity", "bose-einstein",
    "fermi-dirac", "maxwell-boltzmann", "planck", "einstein", "debye",
    "drude", "lorentz", "sommerfeld", "bloch", "wannier", "tight-binding",
    "kohn-sham", "hartree-fock", "density-functional", "dft", "lda", "gga",
    "hybrid", "mgga", "gw", "bse", "td-dft", "ci", "cc", "mp2", "mp3",
    "mp4", "fci", "qmc", "dmc", "afqmc", "path-integral", "molecular-dynamics",
    "md", "aimd", "cpmd", "born-oppenheimer", "car-parrinello", "metadynamics",
    "umbrella-sampling", "replica-exchange", "simulated-annealing", "genetic",
    "monte-carlo", "wang-landau", "multicanonical", "parallel-tempering",
    "tempering", "histogram", "wham", "mbar", "tpm", "transition-path",
    "commitment", "mfpt", "rate-theory", "kramers", "arrhenius", "eyring",
    "marcus", "levich", "landauer", "buttiker", "nscf", "scf", "diis",
    "pulay", "davidson", "lanczos", "arnoldi", "jacobi-davidson", "rpa",
    "tda", "stda", "sos", "cis", "cid", "cisd", "fci", "casscf", "caspt2",
    "nevpt2", "dmrg", "tensor-network", "mps", "mpo", "peps", "mera",
    "tebd", "dmrg", "tdvp", "variational", "projector", "qpe", "vqe",
    "qaoa", "qml", "quantum-machine-learning", "quantum-simulation",
    "quantum-error-correction", "surface-code", "color-code", "stabilizer",
    "topological", "anyon", "braiding", "fusion", "modular", "conformal",
    "cft", "2d-cft", "3d-cft", "holography", "ads-cft", "gauge-gravity",
    "string-theory", "m-theory", "f-theory", "brane", "d-brane", "m-brane",
    "ns-brane", "d-instanton", "calabi-yau", "g2", "spin7", "hyperkähler",
    "quaternionic", "kähler", "complex", "symplectic", "riemannian",
    "pseudo-riemannian", "lorentzian", "euclidean", "conformal", "projective",
    "affine", "metric", "connection", "curvature", "torsion", "holonomy",
    "geodesic", "jacobi-field", "conjugate-point", "cut-locus", "injectivity",
    "convexity", "comparison", "toponogov", "bishop-gromov", "cheeger-gromoll",
    "splitting", " soul", "perelman", "hamilton", "ricci-flow", "yamabe",
    "conformal-mapping", "quasiconformal", "teichmüller", "moduli",
    "deformation", "kodaira-spencer", "hodge", "mixed-hodge", "variation",
    "period", "abelian-variety", "jacobian", "theta-function", "modular-form",
    "automorphic", "langlands", "shimura", "deligne", "mumford", "faltings",
    "wiles", "taylor", "breuil", "conrad", "diamond", "fontaine", "mazur",
    "serre", "grothendieck", "artin", "weil", "hasse", "minkowski", "hilbert",
    "noether", "emmy", "ramanujan", "hardy", "littlewood", "turing", "church",
    "kleene", " gödel", "tarski", "skolem", "herbrand", "gentzen", " curry",
    "howard", "de-bruijn", "automath", "lf", "twelf", "isabelle", "coq",
    "agda", "lean", "idris", "fstar", "hol", "hol-light", "pvs", "nuprl",
    "acl2", "metamath", "mizar", "proofpeer", "dedukti", "lambda-pi",
    "cubical", "homotopy", "hott", "cubical-type-theory", "cartesian",
    "computational", "algorithmic", "complexity", "np", "p", "np-complete",
    "np-hard", "approximation", "ptas", "fptas", "fpt", "parameterized",
    "fixed-parameter", "kernelization", "treewidth", "cliquewidth",
    "branchwidth", "pathwidth", "bandwidth", "cutwidth", "carvingwidth",
    "treedepth", "vertex-cover", "clique", "independent-set", "dominating-set",
    "hitting-set", "set-cover", "knapsack", "bin-packing", "scheduling",
    "tsp", "vehicle-routing", "facility-location", "network-design",
    "spanning-tree", "steiner-tree", "traveling-salesman", "hamiltonian",
    "eulerian", "matching", "b-matching", "flow", "min-cut", "max-cut",
    "multiway-cut", "multicut", "sparsest-cut", "expander", "spectral",
    "algebraic", "probabilistic", "derandomization", "pcp", "unique-games",
    "small-set-expansion", "sum-of-squares", "sos", "lp", "sdp", "copositive",
    "completely-positive", "doubly-nonnegative", "psd", "second-order",
    "power-cone", "exponential-cone", "geometric", "conic", "semi-infinite",
    "robust", "stochastic", "chance-constrained", "bilevel", "multiobjective",
    "pareto", "nash", "stackelberg", "mechanism-design", "auction", "matching",
    "market", "equilibrium", "competitive", "walrasian", "scarf", "arrow-debreu",
    "computational-social-choice", "voting", "fair-division", "allocation",
    "envy-free", "proportionality", "maximin", "nash-welfare", "leximin",
    "egalitarian", "utilitarian", "rawlsian", "prioritarian", "sufficientarian",
    "capabilities", "functionings", "flourishing", "wellbeing", "happiness",
    "life-satisfaction", "positive-psychology", "flow-experience", "mindfulness",
    "meditation", "cognitive-behavioral", "act", "dbt", "mbct", "mbsr",
    "acceptance", "commitment", "dialectical", "behavior", "schema",
    "emotion", "regulation", "distress-tolerance", "interpersonal",
    "effectiveness", "assertiveness", "communication", "conflict-resolution",
    "negotiation", "mediation", "arbitration", "litigation", "adr",
    "restorative", "transformative", "peacemaking", "reconciliation",
    "forgiveness", "gratitude", "empathy", "compassion", "altruism",
    "prosocial", "cooperation", "coordination", "collaboration", "collective",
    "intelligence", "wisdom", "crowds", "swarm", "hive", "superorganism",
    "emergence", "self-organization", "spontaneous", "order", "chaos",
    "complexity", "nonlinearity", "bifurcation", "attractor", "strange",
    "fractal", "scale-free", "small-world", "network", "graph", "hypergraph",
    "simplicial", "cellular", "topological-data-analysis", "tda", "persistent",
    "homology", "cohomology", "homotopy", "fundamental-group", "covering",
    "fiber-bundle", "vector-bundle", "principal-bundle", "associated",
    "connection", "covariant-derivative", "parallel-transport", "holonomy",
    "curvature", "torsion", "metric", "riemannian", "pseudo-riemannian",
    "symplectic", "complex", "kähler", "hyperkähler", "quaternionic",
    "spin", "spinor", "dirac", "weyl", "majorana", "killing", "killing-spinor",
    "g2", "spin7", "calabi-yau", "special-holonomy", "reduced-holonomy",
    "berger", "joyce", "tian", "yau", "donaldson", "uhlenbeck", "taubes",
    "witten", "seiberg", "floer", "instanton", "monopole", "vortex",
    "soliton", "lump", "skyrmion", "domain-wall", "cosmic-string",
    "texture", "defect", "dislocation", "disclination", "disgyration",
    "hedgehog", "monopole", "dyon", "anyonic", "nonabelian", "topological",
    "protected", "degenerate", "ground-state", "excited-state", "gapless",
    "gapped", "critical", "quantum-critical", "kondo", "anderson", "hubbard",
    "t-j", "heisenberg", "ising", "xy", "potts", "clock", "o-n", "chiral",
    "nonlinear-sigma", "wess-zumino", "wess-zumino-witten", "gross-neveu",
    "thirring", "schwinger", "qed", "qcd", "electroweak", "gws", "sm",
    "mssm", "nmssm", "lrsm", "gut", "so10", "su5", "flipped-su5",
    "trinification", "331", "technicolor", "composite", "preon", "rishon",
    "paton", "harari", "shupe", "string", "superstring", "heterotic",
    "type-i", "type-iia", "type-iib", "m-theory", "f-theory", "s-duality",
    "t-duality", "u-duality", "mirror-symmetry", "symplectic-mirror",
    "homological-mirror", "stability", "bridgeland", "pi-stability",
    "t-stability", "geometric-invariant", "git", "mumford", "hilbert-scheme",
    "quot-scheme", "moduli-space", "stack", "derived", "infinity",
    "higher", "n-category", "n-groupoid", "quasicategory", "simplicial",
    "dendroidal", "operad", "prop", "properad", "wheeled", "modular",
    "cyclic", "symplectic", "poisson", "lie", "lie-algebroid", "courant",
    "dirac", "generalized-complex", "generalized-kähler", "hyperkähler",
    "torsion", "nonholonomic", "subriemannian", "carnot-carathéodory",
    "cc-distance", "pansu", "mitchell", "chow", "ráshevsky", "gromov",
    "hausdorff", "box", "packing", "covering", "minkowski", "fractal",
    "spectral-dimension", "walk-dimension", "diffusion", "heat-kernel",
    "laplacian", "dirichlet", "neumann", "robin", "mixed", "transmission",
    "interface", "contact", "obstacle", "free-boundary", "stefan",
    "mullins-sekerka", "cahn-hilliard", "allen-cahn", "phase-field",
    "level-set", "volume-of-fluid", "front-tracking", "immersed-boundary",
    "fictitious-domain", "penalty", "lagrange-multiplier", "augmented",
    "uzawa", "arrow-hurwicz", "primal-dual", "admm", "proximal", "operator",
    "splitting", "douglas-rachford", "peaceman-rachford", "alternating",
    "direction", "implicit", "explicit", "semi-implicit", "crank-nicolson",
    "runge-kutta", "adams-bashforth", "adams-moulton", "bdf", "leapfrog",
    "verlet", "velocity-verlet", "symplectic", "geometric", "variational",
    "discrete", "multisymplectic", "energy-momentum", "mimetic", "compatible",
    "structure-preserving", "physics-informed", "neural", "operator-learning",
    "fourier", "spectral", "polynomial", "wavelet", "radial-basis", "meshfree",
    "particle", "sph", "mls", "rkpm", "element-free", "boundary-element",
    "finite-element", "finite-volume", "finite-difference", "spectral-element",
    "discontinuous-galerkin", "continuous-galerkin", "hybridizable",
    "weak-galerkin", "virtual-element", "polygonal", "polyhedral", "cut-cell",
    "immersed", "unfitted", "embedded", "level-set", "xfem", "gfem", "pu",
    "enrichment", "partition-of-unity", "generalized", "extended",
    "scaled-boundary", "isogeometric", "nurbs", "t-spline", "subdivision",
    "catmull-clark", "doo-sabin", "loop", "butterfly", "modified-butterfly",
    "sqrt3", "dual", "primal", "combined", "hybrid", "multiresolution",
    "wavelet", "lift", "second-generation", "sweldens", "donoho",
    "curvelet", "ridgelet", "shearlet", "contourlet", "bandlet", "wedgelet",
    "beamlet", "platelet", "surflet", "volumelet", "gaussian", "hermite",
    "laguerre", "legendre", "chebyshev", "jacobi", "gegenbauer", "zernike",
    "spherical-harmonic", "bessel", "hankel", "airy", "struve", "lommel",
    "kelvin", "anger", "webber", "parabolic-cylinder", "confluent",
    "hypergeometric", "whittaker", "mathieu", "elliptic", "theta", "weierstrass",
    "gamma", "beta", "psi", "zeta", "polygamma", "incomplete-gamma",
    "incomplete-beta", "error-function", "fresnel", "dawson", "exponential",
    "logarithmic", "sine-integral", "cosine-integral", "hyperbolic-sine",
    "hyperbolic-cosine", "fermi-dirac", "bose-einstein", "debye", "plasma",
    "voigt", "pseudo-voigt", "pearson", "student-t", "chi-squared", "f-distribution",
    "beta-distribution", "gamma-distribution", "weibull", "gumbel", "fréchet",
    "gev", "stable", "levy", "cauchy", "laplace", "logistic", "log-normal",
    "inverse-gaussian", "wald", "inverse-gamma", "inverse-chi-squared",
    "scaled-inverse-chi-squared", "pareto", "log-logistic", "burr", "dagum",
    "singh-maddala", "gb2", "skew-normal", "skew-t", "sinh-arcsinh",
    "jones-pewsey", "wrapped", "von-mises", "kent", "fisher-bingham",
    "bingham", "watson", "dimroth-watson", "wood", "projected", "offset",
    "spherical", "circular", "directional", "compositional", "simplex",
    "dirichlet", "logistic-normal", "additive-log-ratio", "isometric-log-ratio",
    "pairwise-log-ratio", "symmetric", " Pivot", "balance", "ilr", "clr",
    "alr", "phl", "rhl", "constrained", "ordination", "pca", "pcoa", "nmds",
    "rda", "cca", "dca", "decorana", "twinspan", "indicator-species",
    "analysis", "isa", "multivariate", "regression-tree", "mars", "earth",
    "gradient-boosting", "xgboost", "lightgbm", "catboost", "random-forest",
    "extra-trees", "adaboost", "gbm", "h2o", "spark-mllib", "scikit-learn",
    "tensorflow", "pytorch", "jax", "flax", "haiku", "optax", "trax",
    "t5x", "mesh", "pax", "praxis", "lingvo", "seqio", "t5", "bart",
    "pegasus", "prophetnet", "unilm", "ernie", "bert", "roberta", "albert",
    "electra", "deberta", "mpnet", "xlnet", "longformer", "bigbird",
    "reformer", "performer", "linformer", "nystromformer", "linear",
    "attention", "routing", "mixture-of-experts", "moe", "switch",
    "gshard", "t5x", "paLM", "gpt", "gpt-2", "gpt-3", "gpt-4", "gpt-4o",
    "gpt-4-turbo", "gpt-4-vision", "claude", "claude-2", "claude-3",
    "claude-3-opus", "claude-3-sonnet", "claude-3-haiku", "gemini",
    "gemini-pro", "gemini-ultra", "gemini-1.5", "llama", "llama-2",
    "llama-3", "llama-3.1", "mistral", "mixtral", "codestral", "phi",
    "phi-2", "phi-3", "phi-4", "falcon", "mpt", "dolly", "alpaca",
    "vicuna", "wizardlm", "openchat", "openhermes", "neural-chat",
    "stablelm", "redpajama", "gpt-j", "gpt-neox", "gpt-neo", "pythia",
    "opt", "bloom", "bloomz", "mt0", "mt5", "umt5", "byt5", "t0",
    "tk-instruct", "super-natural-instructions", "natural-instructions",
    "flan", "flan-t5", "flan-ul2", "coig", "belle", "firefly", "baichuan",
    "chatglm", "chatglm-2", "chatglm-3", "qwen", "qwen-2", "yi",
    "internlm", "deepseek", "deepseek-coder", "deepseek-math", "codegeex",
    "codegeex-2", "starcoder", "starcoder-2", "codellama", "codefuse",
    "codeqwen", "codelm", "codelm-7b", "wizardcoder", "phind", "continue",
    "aider", "cursor", "copilot", "codeium", "tabnine", "replit", "ghostwriter",
    "amazon-codewhisperer", "google-codey", "github-copilot", "copilot-chat",
    "copilot-workspace", "devin", "swe-agent", "open-devin", "metagpt",
    "autogpt", "babyagi", "gpt-engineer", "aider", "continue", "supermaven",
    "sourcegraph-cody", "tabby", "continue", "cline", "roo-code", "void",
    "zed", "trae", "windsurf", "bolt", "lovable", "v0", "tempo", "lovable",
    "vibe-coding", "ai-coding", "agentic-coding", "cursor-composer",
    "claude-artifacts", "shadcn", "magic-patterns", "languine", "lingui",
    "i18n", "localization", "internationalization", "globalization",
    "multilingual", "cross-lingual", "zero-shot-translation", "machine-translation",
    "nmt", "seq2seq", "attention-is-all-you-need", "transformer",
    "BERT", "RoBERTa", "DeBERTa", "ELECTRA", "XLNet", "ALBERT", "DistilBERT",
    "MobileBERT", "TinyBERT", "FastBERT", "Q-BERT", "I-BERT", "SparseBERT",
    "PruneBERT", "FreezeBERT", "BitFit", "Adapter", "LoRA", "QLoRA",
    "DoRA", "PiSSA", "Bone", "LoKR", "LoHA", "DyLoRA", "AdaLoRA",
    "S-LoRA", "vLLM", "TensorRT-LLM", "DeepSpeed", "Megatron-LM",
    "Fairseq", "HuggingFace", "Transformers", "Datasets", "Tokenizers",
    "Accelerate", "PEFT", "TRL", "TRLX", "LMFlow", "Llama-Factory",
    "Axolotl", "Unsloth", "MergeKit", "TIES", "DARE", "TaskArithmetic",
    "ModelSoups", "FrankenMoE", "Mixture-of-Depths", "Mixtral",
    "SparseMixtral", "Qwen-MoE", "DeepSeek-MoE", "DBRX", "Grok",
    "Jamba", "Mamba", "Mamba-2", "RWKV", "RetNet", "YOCO", "Moonlight",
    "TTT", "RNN", "LSTM", "GRU", "QRNN", "SRU", "IndRNN", "JANET",
    "Zoneout", "HyperLSTM", "LayerNorm", "BatchNorm", "GroupNorm",
    "InstanceNorm", "RMSNorm", "PowerNorm", "SpectralNorm", "WeightNorm",
    "CosineNorm", "Evonorm", "FRN", "FilterResponseNorm", "Squeeze-and-Excitation",
    "CBAM", "ECA", "SKNet", "ResNeXt", "DenseNet", "EfficientNet",
    "MobileNet", "ShuffleNet", "GhostNet", "RegNet", "ConvNeXt",
    "Swin-Transformer", "Vision-Transformer", "DeiT", "BEiT", "MAE",
    "iBOT", "data2vec", "DINO", "DINOv2", "MoCo", "SimCLR", "BYOL",
    "SwAV", "Barlow-Twins", "VICReg", "W-MSE", "NNCLR", "Twist",
    "Fast-MoCo", "Quick-MoCo", "Empirical-Bayes", "Stein", "SGLD",
    "SVGD", "KSD", "MMD", "Energy", "Score", "Flow", "Diffusion",
    "DDPM", "DDIM", "Score-SDE", "Latent-Diffusion", "Stable-Diffusion",
    "Imagen", "DALL-E", "DALL-E-2", "DALL-E-3", "Midjourney", "Firefly",
    "PixelCNN", "WaveNet", "Tacotron", "FastSpeech", "MelGAN", "HiFi-GAN",
    "Parallel-WaveGAN", "VITS", "Bark", "Tortoise", "StyleTTS", "NaturalSpeech",
    "VALL-E", "VoiceBox", "Audiobox", "MusicGen", "MusicLM", "Jukebox",
    "Magenta", "DDSP", "NSynth", "GANSynth", "MelNet", "WaveRNN",
    "WaveGlow", "Flowtron", "Glow-TTS", "Flow-TTS", "FastPitch",
    "OverFlow", "Neural-HMM", "Grad-TTS", "PortaSpeech", "P-Flow",
    "Matcha-TTS", "MeloTTS", "Coqui", "Piper", "Espeak", "Festival",
    "Flite", "MaryTTS", "OpenJTalk", "Kaldi", "ESPnet", "WeNet",
    "Whisper", "WhisperX", "Faster-Whisper", "Distil-Whisper",
    "Wav2Vec", "Wav2Vec-2", "HuBERT", "Data2Vec", "UniSpeech",
    "SpeechT5", "MMS", "VoxPopuli", "MLS", "Common-Voice", "LibriSpeech",
    "TED-LIUM", "AISHELL", "CSJ", "GigaSpeech", "SPGISpeech", "NVIDIA-NeMo",
    "Triton", "TensorRT", "ONNX", "ONNX-Runtime", "OpenVINO", "CoreML",
    "MLX", "GGML", "llama.cpp", "Ollama", "LocalAI", "text-generation-webui",
    "koboldcpp", "rwkv.cpp", "mamba.cpp", "exllama", "exllamav2",
    "AutoGPTQ", "AutoAWQ", "GPTQ", "AWQ", "GGUF", "GGML", "Q4_0",
    "Q4_1", "Q5_0", "Q5_1", "Q8_0", "FP16", "BF16", "INT8", "INT4",
    "SmoothQuant", "GPTQ", "AWQ", "SpQR", "AQLM", "QuIP", "QuIP#",
    "FineGrained", "BitDistiller", "OmniQuant", "LLM-QAT", "RPTQ",
    "ZeroQuant", "LLM.int8", "QLoRA", "BitsAndBytes", "NormalFloat",
    "GPTQ-Triton", "Marlin", "Mixtral-Marlin", "FP8", "E4M3", "E5M2",
    "Blockwise", "Dynamic", "Static", "Activation-Aware", "Weight-Only",
    "KV-Cache", "PagedAttention", "FlashAttention", "FlashAttention-2",
    "FlashDecoding", "FlashInfer", "vLLM", "TensorRT-LLM", "DeepSpeed-Inference",
    "Text-Generation-Inference", "TGI", "HuggingFace-Text-Generation-Inference",
    "NVIDIA-Triton", "Triton-TensorRT-LLM", "Triton-vLLM", "SGLang",
    "LMDeploy", "MLC-LLM", "llamafile", "Ollama", "llama.cpp", "whisper.cpp",
    "stable-diffusion.cpp", "llava.cpp", "Bark.cpp", "TTS",
    "edge-tts", "pyttsx3", "gTTS", "coqui-tts", "mimic3", "piper-tts",
    "espeak-ng", "mbrola", "festival", "flite", "spd-say", "say",
    "speech-dispatcher", "espeak", "pico-tts", "svox", "acapela",
    "nuance", "ivona", "polly", "azure-tts", "google-cloud-tts",
    "ibm-watson-tts", "microsoft-azure-speech", "amazon-polly",
    "alibaba-nls", "tencent-cloud-tts", "baidu-speech", "iflytek",
    "sensetime", "yitu", "cloudwalk", "megvii", "face++", "商汤",
    "旷视", "依图", "云从", "科大讯飞", "百度", "阿里", "腾讯",
    "华为", "字节跳动", "美团", "滴滴", "小米", "OPPO", "vivo",
    "大疆", "地平线", "寒武纪", "燧原", "壁仞", "摩尔线程", "天数智芯",
    "沐曦", "瀚博", "登临", "鲲云", "清微", "知存", "后摩",
    "芯驰", "黑芝麻", "小马智行", "momenta", "文远知行", "AutoX",
    "百度Apollo", "华为ADS", "小鹏XNGP", "蔚来NOP", "理想NOA",
    "特斯拉FSD", "Waymo", "Cruise", "Zoox", "Aurora", "Argo",
    "Mobileye", "Comma.ai", "Torc", "Nuro", "Pony.ai", "WeRide",
}

EMPTY_WORDS_CN = {
    "赋能", "抓手", "闭环", "打通", "全链路", "底层逻辑", "颗粒度",
    "对齐", "拉通", "沉淀", "强大的", "革命性的",
}

EMPTY_WORDS_EN = {
    "groundbreaking", "revolutionary", "game-changing", "game changing",
    "cutting-edge", "cutting edge", "world-class", "world class",
    "best-in-class", "best in class", "industry-leading", "industry leading",
    "next-generation", "next generation", "state-of-the-art", "state of the art",
    "bleeding-edge", "bleeding edge", "disruptive", "innovative",
    "transformative", "pioneering", "trailblazing", "paradigm-shifting",
    "paradigm shifting", "seamless", "holistic", "synergistic",
    "scalable", "robust", "streamlined", "optimized", "enhanced",
    "leverage", "utilize", "synergy", "paradigm",
}

ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+-\d{8}-\d{3}$")
URL_PATTERN = re.compile(r"^https?://")


def _count_chars(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


def _score_summary(summary: str) -> tuple[float, list[str]]:
    feedback: list[str] = []
    char_count = _count_chars(summary)

    if char_count >= 50:
        score = 25.0
        feedback.append(f"摘要长度 {char_count} 字，达到满分标准")
    elif char_count >= 20:
        score = 15.0
        feedback.append(f"摘要长度 {char_count} 字，达到基本分")
    else:
        score = max(0.0, char_count / 20 * 15)
        feedback.append(f"摘要长度 {char_count} 字，低于 20 字基本要求")

    tech_found = [kw for kw in TECH_KEYWORDS if kw.lower() in summary.lower()]
    if tech_found:
        bonus = min(5.0, len(tech_found) * 1.0)
        score = min(25.0, score + bonus)
        feedback.append(f"含技术关键词: {', '.join(tech_found[:3])}")

    return score, feedback


def _score_depth(score_value: Any) -> tuple[float, list[str]]:
    feedback: list[str] = []
    if score_value is None:
        return 0.0, ["缺少 score 字段，无法评估技术深度"]
    if not isinstance(score_value, (int, float)):
        return 0.0, [f"score 类型错误: {type(score_value).__name__}"]
    mapped = max(0.0, min(25.0, float(score_value) / 10 * 25))
    feedback.append(f"score={score_value}，映射为 {mapped:.1f}/25")
    return mapped, feedback


def _score_format(data: dict[str, Any]) -> tuple[float, list[str]]:
    feedback: list[str] = []
    score = 0.0
    checks = [
        ("id", lambda v: isinstance(v, str) and ID_PATTERN.match(v)),
        ("title", lambda v: isinstance(v, str) and len(v.strip()) > 0),
        ("source_url", lambda v: isinstance(v, str) and URL_PATTERN.match(v)),
        ("status", lambda v: isinstance(v, str) and v in {"draft", "review", "published", "archived"}),
        ("timestamp", lambda v: any(k in data for k in ("published_at", "collected_at", "created_at", "updated_at"))),
    ]

    for name, check in checks:
        if name == "timestamp":
            ok = check(None)
        else:
            ok = name in data and check(data[name])
        if ok:
            score += 4.0
            feedback.append(f"{name}: 符合规范")
        else:
            feedback.append(f"{name}: 不符合规范")

    return score, feedback


def _score_tags(tags: Any) -> tuple[float, list[str]]:
    feedback: list[str] = []
    if not isinstance(tags, list):
        return 0.0, ["tags 不是列表"]

    if len(tags) == 0:
        return 0.0, ["缺少标签"]

    if 1 <= len(tags) <= 3:
        score = 15.0
        feedback.append(f"标签数量 {len(tags)}，在最佳范围内")
    elif len(tags) <= 5:
        score = 10.0
        feedback.append(f"标签数量 {len(tags)}，偏多")
    else:
        score = 5.0
        feedback.append(f"标签数量 {len(tags)}，过多")

    valid_tags = [t for t in tags if isinstance(t, str) and t.lower() in STANDARD_TAGS]
    invalid_tags = [t for t in tags if isinstance(t, str) and t.lower() not in STANDARD_TAGS]

    if invalid_tags:
        score = max(0.0, score - len(invalid_tags) * 2)
        feedback.append(f"非标准标签: {', '.join(map(str, invalid_tags[:3]))}")

    if valid_tags:
        feedback.append(f"标准标签: {', '.join(valid_tags[:3])}")

    return max(0.0, score), feedback


def _score_empty_words(text: str) -> tuple[float, list[str]]:
    feedback: list[str] = []
    if not isinstance(text, str):
        return 0.0, ["文本类型错误"]

    found_cn = [w for w in EMPTY_WORDS_CN if w in text]
    found_en = [w for w in EMPTY_WORDS_EN if w.lower() in text.lower()]

    total_found = len(found_cn) + len(found_en)

    if total_found == 0:
        return 15.0, ["未检测到空洞词"]

    penalty = min(15.0, total_found * 3)
    score = max(0.0, 15.0 - penalty)

    if found_cn:
        feedback.append(f"中文空洞词: {', '.join(found_cn)}")
    if found_en:
        feedback.append(f"英文空洞词: {', '.join(found_en)}")

    return score, feedback


def evaluate_file(path: Path) -> QualityReport:
    report = QualityReport(file_path=path)

    if not path.exists():
        report.dimensions.append(DimensionScore("文件存在", 0, 0, ["文件不存在"]))
        return report

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        report.dimensions.append(DimensionScore("JSON解析", 0, 0, [str(exc)]))
        return report

    if not isinstance(data, dict):
        report.dimensions.append(DimensionScore("数据结构", 0, 0, ["根节点不是对象"]))
        return report

    summary = data.get("summary", "")
    score_val = data.get("score")
    tags = data.get("tags", [])
    text_to_check = f"{data.get('title', '')} {summary}"

    s, fb = _score_summary(summary)
    report.dimensions.append(DimensionScore("摘要质量", s, 25.0, fb))

    s, fb = _score_depth(score_val)
    report.dimensions.append(DimensionScore("技术深度", s, 25.0, fb))

    s, fb = _score_format(data)
    report.dimensions.append(DimensionScore("格式规范", s, 20.0, fb))

    s, fb = _score_tags(tags)
    report.dimensions.append(DimensionScore("标签精度", s, 15.0, fb))

    s, fb = _score_empty_words(text_to_check)
    report.dimensions.append(DimensionScore("空洞词检测", s, 15.0, fb))

    report.total_score = sum(d.score for d in report.dimensions)
    report.max_total = sum(d.max_score for d in report.dimensions)

    pct = report.percentage
    if pct >= 80:
        report.grade = "A"
    elif pct >= 60:
        report.grade = "B"
    else:
        report.grade = "C"

    return report


def _progress_bar(score: float, max_score: float, width: int = 30) -> str:
    if max_score == 0:
        return "[" + " " * width + "]"
    ratio = score / max_score
    filled = int(width * ratio)
    empty = width - filled
    bar = "█" * filled + "░" * empty
    pct = ratio * 100
    return f"[{bar}] {pct:.1f}%"


def _is_glob(pattern: str) -> bool:
    return "*" in pattern or "?" in pattern or "[" in pattern


def collect_files(patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()

    for pattern in patterns:
        p = Path(pattern)
        if _is_glob(pattern):
            matches = list(Path(".").glob(pattern))
            if not matches:
                print(f"Warning: no files matched pattern '{pattern}'", file=sys.stderr)
            for match in matches:
                if match.is_file() and match not in seen:
                    files.append(match)
                    seen.add(match)
        elif p.exists():
            if p.is_file() and p not in seen:
                files.append(p)
                seen.add(p)
            elif p.is_dir():
                print(f"Warning: '{pattern}' is a directory, skipping", file=sys.stderr)
        else:
            matches = list(Path(".").glob(pattern))
            if matches:
                for match in matches:
                    if match.is_file() and match not in seen:
                        files.append(match)
                        seen.add(match)
            else:
                print(f"Warning: file not found '{pattern}'", file=sys.stderr)

    return files


def print_report(report: QualityReport) -> None:
    print(f"\n{'='*60}")
    print(f"📄 {report.file_path}")
    print(f"{'='*60}")

    for dim in report.dimensions:
        bar = _progress_bar(dim.score, dim.max_score)
        print(f"\n  {dim.name:10s} {dim.score:5.1f}/{dim.max_score:.0f}  {bar}")
        for fb in dim.feedback:
            print(f"             → {fb}")

    total_bar = _progress_bar(report.total_score, report.max_total, width=40)
    print(f"\n  {'总计':10s} {report.total_score:5.1f}/{report.max_total:.0f}  {total_bar}")

    grade_emoji = {"A": "🅰️", "B": "🅱️", "C": "🌊"}.get(report.grade, "❓")
    print(f"\n  等级: {grade_emoji} {report.grade} ({report.percentage:.1f}%)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Quality scoring for knowledge entry JSON files."
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="JSON file(s) to evaluate. Supports wildcards (e.g., *.json).",
    )
    args = parser.parse_args()

    files = collect_files(args.files)

    if not files:
        print("Error: No valid files to evaluate.", file=sys.stderr)
        return 1

    reports: list[QualityReport] = []
    has_grade_c = False

    for file_path in files:
        report = evaluate_file(file_path)
        reports.append(report)
        print_report(report)
        if report.grade == "C":
            has_grade_c = True

    if len(files) > 1:
        print(f"\n{'='*60}")
        print("📊 汇总")
        print(f"{'='*60}")

        total = len(reports)
        grades = {"A": 0, "B": 0, "C": 0}
        for r in reports:
            grades[r.grade] = grades.get(r.grade, 0) + 1

        print(f"  总计: {total} 文件")
        for g in ("A", "B", "C"):
            pct = grades[g] / total * 100 if total > 0 else 0
            print(f"  {g} 级: {grades[g]:3d} ({pct:5.1f}%)")

        avg_score = sum(r.total_score for r in reports) / total if total > 0 else 0
        print(f"  平均分: {avg_score:.1f}")

    return 1 if has_grade_c else 0


if __name__ == "__main__":
    sys.exit(main())
