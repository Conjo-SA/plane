/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Mail, MessageCircle, MessageSquare } from "lucide-react";
import { EProductSubscriptionEnum } from "@plane/types";
// plane imports
import { cn } from "@plane/utils";

export type TPlanFeatureData = React.ReactNode | boolean | null;

// TODO: we should change this type and use TProductSubscriptionType instead. Need changes in common constants.
export type TPlanePlans = "free" | "one" | "pro" | "business" | "enterprise";

export type TPlanDetail = {
  id: EProductSubscriptionEnum;
  name: React.ReactNode;
  monthlyPrice?: number;
  yearlyPrice?: number;
  monthlyPriceSecondaryDescription?: React.ReactNode;
  yearlyPriceSecondaryDescription?: React.ReactNode;
  buttonCTA?: React.ReactNode;
  isActive: boolean;
};

type TPlanFeatureDetails = {
  title: React.ReactNode;
  description?: React.ReactNode;
  selfHostedDescription?: React.ReactNode;
  comingSoon?: boolean;
  selfHostedOnly?: boolean;
  cloud: Record<TPlanePlans, TPlanFeatureData>;
  "self-hosted"?: Record<TPlanePlans, TPlanFeatureData>;
};

type TPlansComparisonDetails = {
  id: string;
  title: React.ReactNode;
  comingSoon?: boolean;
  cloudOnly?: boolean;
  selfHostedOnly?: boolean;
  features: TPlanFeatureDetails[];
};

type PlanePlans = {
  planDetails: Record<TPlanePlans, TPlanDetail>;
  planHighlights: Record<TPlanePlans, string[]>;
  planComparison: TPlansComparisonDetails[];
};

function ForumIcon({ className }: { className?: string }) {
  return <MessageSquare className={cn(className, "size-5 text-secondary")} />;
}

export function ComingSoonBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "w-fit rounded-sm bg-accent-primary px-1.5 py-0.5 text-9 font-semibold whitespace-nowrap text-on-color",
        className
      )}
    >
      EM BREVE
    </span>
  );
}

export const PLANS_LIST: TPlanePlans[] = ["free", "one", "pro", "business", "enterprise"];

export const PLANS_COMPARISON_LIST: TPlansComparisonDetails[] = [
  {
    id: "project-work-tracking",
    title: "Projetos + acompanhamento do trabalho",
    features: [
      {
        title: "Projetos",
        description: "Crie projetos para reunir tarefas, ciclos e módulos.",
        cloud: {
          free: true,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Tarefas",
        description:
          "Registre o trabalho em tarefas, defina propriedades para acompanhamento e adicione\na ciclos ou módulos.",
        cloud: {
          free: true,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Comentários",
        description: "Responda em tarefas, @mencione membros e troque ideias\nsem sair do Tasks.",
        cloud: {
          free: true,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Ciclos",
        description: "Acompanhe o trabalho em períodos com frequências diferentes.",
        cloud: {
          free: true,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Módulos",
        description: "Agrupe trabalho replicável em módulos com seus próprios\nresponsáveis.",
        cloud: {
          free: true,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Entrada",
        description:
          "Veja sugestões e feedback de visitantes e\nconvidados antes de decidir adicioná-los ao seu\nprojeto.",
        cloud: {
          free: true,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Estimativas",
        description: "Meça o esforço em pontos, num sistema que funciona para\nvocê.",
        cloud: {
          free: "Básico",
          one: "Básico",
          pro: "Avançado",
          business: "Avançado",
          enterprise: "Avançado",
        },
      },
    ],
  },
  {
    id: "project-work-management",
    title: "Gestão de projetos + trabalho",
    features: [
      {
        title: "Operações em massa",
        description: "Adicione várias tarefas a ciclos ou módulos, transfira-as\nou edite suas propriedades.",
        cloud: {
          free: false,
          one: "Propriedades limitadas",
          pro: "Todas as propriedades",
          business: (
            <span className="flex flex-col items-end gap-1 lg:items-center">
              <ComingSoonBadge />
              Transferências e conversões de tarefas
            </span>
          ),
          enterprise: (
            <span className="flex flex-col items-end gap-1 lg:items-center">
              <ComingSoonBadge />
              Transferências e conversões de tarefas
            </span>
          ),
        },
      },
      {
        title: "Controle de tempo + registros de trabalho",
        description: "Registre o tempo por tarefa, veja relatórios consolidados e\nfiltre conforme a necessidade.",
        cloud: {
          free: false,
          one: "Básico",
          pro: "Histórico de apontamentos",
          business: "Histórico de apontamentos\ne aprovações",
          enterprise: "Histórico de apontamentos\ne aprovações",
        },
      },
      {
        title: "Ciclos ativos",
        description: "Veja todos os ciclos em andamento em todos os projetos ou, em breve, em\num único projeto.",
        cloud: {
          free: false,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Tipos de tarefa",
        description: "Crie seus próprios tipos de tarefa com suas próprias\npropriedades.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Propriedades personalizadas",
        description: "Crie suas próprias propriedades e aplique-as ao seu\nworkspace ou projeto.",
        cloud: {
          free: false,
          one: false,
          pro: "Propriedades personalizadas\npor projeto",
          business: "Propriedades e consolidações\nno nível do workspace",
          enterprise: "Propriedades e consolidações\nno nível do workspace",
        },
      },
      {
        title: "Dependências no Gantt",
        description: "Ajuste visualmente os cronogramas de tarefas dependentes no\nlayout Gantt.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Transferência de tarefas",
        description: "Mova uma tarefa de um projeto ou ciclo para\noutro.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Transferência automática de tarefas do ciclo",
        description:
          "Transfira tarefas incompletas de um ciclo concluído\npara o próximo ciclo ou para o estado padrão do projeto. ",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Épicos",
        description: "Organize o trabalho de longo prazo em épicos que reúnem tarefas,\nciclos e módulos.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Iniciativas",
        description: "Crie iniciativas para agrupar vários épicos.",
        comingSoon: true,
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Marcos",
        description:
          "Adicione marcos a projetos, épicos e iniciativas para manter sua\nequipe no rumo e reportar o progresso.",
        comingSoon: true,
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Visão geral do módulo",
        description:
          "Assim como na visão geral do ciclo, veja detalhes relevantes e\ngráficos de progresso de cada módulo.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Atribuição automática em módulos",
        description: "Escolha regras de atribuição para as tarefas de um\nmódulo, como Linear, Rodízio ou Capacidade.",
        cloud: {
          free: false,
          one: false,
          pro: "Linear",
          business: "Rodízio e capacidade",
          enterprise: "Rodízio e capacidade",
        },
      },
      // {
      //   title: "Project Overview",
      //   description: "See just-in-time snapshots of your project with\nessential metrics.",
      //   comingSoon: true,
      //   cloud: {
      //     free: false,
      //     one: false,
      //     pro: true,
      //     business: true,
      //     enterprise: true,
      //   },
      // },
      {
        title: "Projetos públicos, privados e secretos",
        description:
          "Projetos públicos são visíveis e acessíveis a\ntodos. Os privados são visíveis, mas exigem aprovação\npara entrar. Projetos secretos não são visíveis nem acessíveis.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Situação dos projetos",
        description:
          "Veja todos os projetos distribuídos por situações que destacam\nos que precisam de atenção e os que estão no rumo.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      // {
      //   title: "Project Updates",
      //   description:
      //     "Keep stakeholders in the loop with a dedicated\nspace for updates that everyone in the project can\nsee.",
      //   comingSoon: true,
      //   cloud: {
      //     free: false,
      //     one: false,
      //     pro: true,
      //     business: true,
      //     enterprise: true,
      //   },
      // },
      {
        title: "Modelos de tarefa predefinidos",
        description:
          "Escolha entre os modelos de tarefa disponíveis, que\npersonalizam tipos de tarefa e propriedades para diversos\ncasos de uso.",
        comingSoon: true,
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Ciclos de equipe",
        description: "Veja vários ciclos de vários projetos de uma só vez.",
        cloud: {
          free: false,
          one: false,
          pro: false,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Modelos de projeto",
        description: "Salve estados, fluxos de trabalho, automações e outras configurações\ndo projeto em modelos.",
        cloud: {
          free: false,
          one: false,
          pro: false,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Linhas de base e desvios",
        description: "Defina linhas de base para o andamento dos seus projetos\ne analise os desvios.",
        cloud: {
          free: false,
          one: false,
          pro: false,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Comunicações agendadas",
        description: "Agende relatórios, notificações e mensagens para\nferramentas de terceiros.",
        cloud: {
          free: false,
          one: false,
          pro: false,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Responsáveis da Entrada",
        description: "Atribua por padrão as tarefas aprovadas da Entrada a um\nmembro.",
        cloud: {
          free: false,
          one: false,
          pro: false,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "SLAs personalizados",
        description: "Defina matrizes de SLA para tarefas com prazo crítico.",
        cloud: {
          free: false,
          one: false,
          pro: false,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Formulários de Entrada",
        description: "Receba tarefas na Entrada a partir de formulários web\nacessíveis externamente.",
        cloud: {
          free: false,
          one: false,
          pro: false,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "E-mails para a Entrada",
        description: "Tenha um endereço de e-mail para registrar tarefas\ndiretamente na Entrada de um projeto.",
        comingSoon: true,
        cloud: {
          free: false,
          one: false,
          pro: false,
          business: true,
          enterprise: true,
        },
      },
    ],
  },
  {
    id: "visualization",
    title: "Visualização",
    features: [
      {
        title: "Layouts",
        description: "Escolha entre os layouts Lista, Quadro, Calendário,\nGantt ou Planilha para suas tarefas.",
        cloud: {
          free: true,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Visualizações",
        description: "Salve opções de ordenação, filtro e exibição de um layout em uma\nvisualização.",
        cloud: {
          free: true,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Visualizações compartilhadas",
        description: "Escolha alguns membros com quem compartilhar uma visualização.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Publicar visualizações",
        description: "Publique uma visualização na internet e deixe seus clientes\ninteragirem com ela.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Dashboards e widgets",
        description: "Crie seus próprios dashboards com widgets personalizados\ne tipos de dados.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
    ],
  },
  {
    id: "analytics-reports",
    title: "Análises + relatórios",
    features: [
      {
        title: "Gráficos de progresso",
        description:
          "Acompanhe o progresso em ciclos, módulos e visões gerais\nem todo o Tasks, sem precisar ir para dashboards\nou Análises.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Relatórios de ciclo",
        description:
          "Gere relatórios de ciclo sob demanda durante e após um\nciclo. Consulte os relatórios a qualquer momento por links permanentes.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Insights",
        description: "Retrospectivas, insights sob demanda, projeções.",
        comingSoon: true,
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      // {
      //   title: "Time Capsule",
      //   description: "Go back in your project's timeline and see point-in-\ntime snapshots.",
      //   comingSoon: true,
      //   cloud: {
      //     free: false,
      //     one: false,
      //     pro: false,
      //     business: true,
      //     enterprise: true,
      //   },
      // },
      {
        title: "Análises avançadas de páginas",
        description:
          "Veja quem está visualizando, compartilhando e comentando\nsuas páginas, além de outras informações úteis.",
        comingSoon: true,
        cloud: {
          free: false,
          one: false,
          pro: false,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Relatórios personalizados",
        description: "Gere relatórios por qualquer dimensão e métrica\nem seu projeto ou workspace.",
        comingSoon: true,
        cloud: {
          free: false,
          one: false,
          pro: false,
          business: true,
          enterprise: true,
        },
      },
    ],
  },
  {
    id: "navigation",
    title: "Navegação",
    features: [
      {
        title: "Power K",
        description: "Acesse quase tudo no Tasks\npelo teclado.",
        cloud: {
          free: true,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      // {
      //   title: "Search",
      //   description: "Search via natural-language queries, operators, or\nPQL",
      //   cloud: {
      //     free: "Basic text search",
      //     one: "Basic text search",
      //     pro: (
      //       <span className="flex flex-col items-end lg:items-center gap-1">
      //         <span className="bg-[#3f76ff] text-on-color font-semibold text-9 p-0.5 w-fit whitespace-nowrap rounded-xs">
      //           COMING SOON
      //         </span>
      //         Operator capsules from text or PQL
      //       </span>
      //     ),
      //     business: (
      //       <span className="flex flex-col items-end lg:items-center gap-1">
      //         <span className="bg-[#3f76ff] text-on-color font-semibold text-9 p-0.5 w-fit whitespace-nowrap rounded-xs">
      //           COMING SOON
      //         </span>
      //         Operator capsules from text or PQL
      //       </span>
      //     ),
      //     enterprise: (
      //       <span className="flex flex-col items-end lg:items-center gap-1">
      //         <span className="bg-[#3f76ff] text-on-color font-semibold text-9 p-0.5 w-fit whitespace-nowrap rounded-xs">
      //           COMING SOON
      //         </span>
      //         Operator capsules from text or PQL
      //       </span>
      //     ),
      //   },
      // },
      {
        title: "PQL",
        description:
          "Use a linguagem de consulta do Tasks na busca, com suporte\na operadores booleanos. Em breve, você poderá escrever consultas\nem linguagem natural.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
    ],
  },
  {
    id: "workspace-user-management",
    title: "Gestão de workspace e usuários",
    features: [
      {
        title: "Limite de membros",
        description: "Número de licenças que podem usar os recursos de gestão de projetos e trabalho",
        selfHostedDescription:
          "Número de usuários suportados pela infraestrutura padrão\nAumente a infraestrutura para ter mais usuários",
        cloud: {
          free: "12",
          one: "",
          pro: "Ilimitado",
          business: "Ilimitado",
          enterprise: "Ilimitado",
        },
        "self-hosted": {
          free: "~50",
          one: "~50",
          pro: "~200",
          business: "~200",
          enterprise: "Ilimitado",
        },
      },
      {
        title: "Funções",
        description: "Escolha uma das quatro funções predefinidas ou crie\nfunções personalizadas com RBAC.",
        cloud: {
          free: "Básico",
          one: "Básico",
          pro: "Funções predefinidas",
          business: "RBAC",
          enterprise: "GAC",
        },
      },
      {
        title: "Convidados",
        description: "Permita que alguns usuários vejam tudo ou apenas suas tarefas em\num projeto.",
        cloud: {
          free: false,
          one: "5 por membro pago",
          pro: "5 por membro pago",
          business: "5 por membro pago",
          enterprise: "5 por membro pago",
        },
      },
      {
        title: "Aprovações",
        description: "Defina aprovações de workspace, projeto e tipo de tarefa para\nadministradores designados.",
        comingSoon: true,
        cloud: {
          free: false,
          one: false,
          pro: false,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Interface de administração",
        description: "Tenha uma visão administrativa para gerenciar as configurações\ndo workspace e dos projetos.",
        cloud: {
          free: false,
          one: false,
          pro: false,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Logs de atividade do workspace",
        description: "Veja logs de atividade filtráveis de todo o\nworkspace.",
        cloud: {
          free: false,
          one: false,
          pro: false,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Logs de auditoria com API",
        description:
          "Veja o log de auditoria de todo o workspace e use APIs para enviar\na atividade do Tasks a sistemas de compliance.",
        comingSoon: true,
        cloud: {
          free: false,
          one: false,
          pro: false,
          business: true,
          enterprise: true,
        },
      },
    ],
  },
  {
    id: "automations-workflows",
    title: "Automações e fluxos de trabalho",
    features: [
      {
        title: "Gatilho e ação",
        description: "Escolha um gatilho e uma ação correspondente para cada\nfluxo de automação.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Automação com decisões e loops",
        description: "Use ações como gatilhos indefinidamente em um\nfluxo de automação.",
        comingSoon: true,
        cloud: {
          free: false,
          one: false,
          pro: false,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Número de automações",
        description: "Número total de fluxos de automação no seu\nworkspace",
        cloud: {
          free: false,
          one: false,
          pro: "5,000",
          business: "10,000",
          enterprise: "Ilimitado",
        },
      },
    ],
  },
  {
    id: "knowledge-management",
    title: "Gestão do conhecimento",
    features: [
      {
        title: "Páginas",
        description: "Crie bases de conhecimento para suas equipes,\nacessíveis e compartilháveis.",
        cloud: {
          free: true,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Colaboração em tempo real",
        description: "Edite uma página junto com membros do seu projeto,\nequipe ou workspace.",
        cloud: {
          free: false,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Tarefas incorporadas",
        description: "Incorpore tarefas de qualquer projeto do qual você seja\nmembro.",
        cloud: {
          free: false,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Vínculo com tarefas",
        description: "Vincule páginas a tarefas em uma seção própria nos detalhes\nda tarefa.",
        cloud: {
          free: false,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Publicar",
        description:
          "Publique suas páginas na web para usuários externos e deixe\nque comentem sem entrar no seu workspace.",
        cloud: {
          free: false,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Wiki",
        description: "Crie wikis ou bases de conhecimento para toda a empresa\nsem criar um projeto.",
        cloud: {
          free: false,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Exportações",
        description: "Exporte o conteúdo das páginas para PDF ou documentos\ncompatíveis com Word.",
        cloud: {
          free: false,
          one: false,
          pro: "Um download\npor vez",
          business: "Downloads em fila",
          enterprise: "Downloads em fila",
        },
      },
      {
        title: "Modelos",
        description: "Use páginas como modelos para seu projeto, equipe ou\nworkspace.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Versões",
        description: "Veja versões restauráveis das edições das suas páginas.",
        cloud: {
          free: false,
          one: false,
          pro: "2 dias",
          business: "3 meses",
          enterprise: "Ilimitado",
        },
      },
      {
        title: "Bancos de dados + fórmulas",
        description:
          "Insira bancos de dados e fórmulas em uma página sem\nse preocupar em perder textos, imagens ou outros tipos de\nconteúdo.",
        comingSoon: true,
        cloud: {
          free: false,
          one: false,
          pro: false,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Páginas aninhadas",
        description: "Páginas dentro de páginas: organize-as\ncomo preferir, revelando o conteúdo\naos poucos.",
        comingSoon: true,
        cloud: {
          free: false,
          one: false,
          pro: false,
          business: "Downloads compatíveis com Word + outros formatos",
          enterprise: "Downloads compatíveis com Word + outros formatos",
        },
      },
    ],
  },
  {
    id: "importers",
    title: "Importadores",
    features: [
      {
        title: "Jira",
        description: "Importe suas tarefas e membros do Jira.",
        cloud: {
          free: "Sem propriedades personalizadas",
          one: "Sem propriedades personalizadas",
          pro: "Com propriedades personalizadas",
          business: "Com propriedades personalizadas",
          enterprise: "Com propriedades personalizadas",
        },
      },
      {
        title: "GitHub",
        description: "Importe suas tarefas e membros do GitHub.",
        cloud: {
          free: "Sem propriedades personalizadas",
          one: "Sem propriedades personalizadas",
          pro: "Com propriedades personalizadas",
          business: "Com propriedades personalizadas",
          enterprise: "Com propriedades personalizadas",
        },
      },
    ],
  },
  {
    id: "integrations",
    title: "Integrações",
    comingSoon: true,
    features: [
      {
        title: "GitHub",
        description:
          "Sincronize tarefas e estados do Tasks com issues e estados\ndo GitHub. Atualize o GitHub automaticamente com a atividade\ndo Tasks e vice-versa.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Slack",
        description: "Receba a atividade do Tasks no Slack e use comandos / no\nSlack para fazer alterações no Tasks.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Zapier",
        description: "Execute automações condicionais (se/então/senão) com o Zapier.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Zendesk",
        description: "Crie tarefas no Tasks a partir de tickets do Zendesk.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Freshdesk",
        description: "Crie tarefas no Tasks a partir de tickets do Freshdesk.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
    ],
  },
  {
    id: "storage",
    title: "Armazenamento",
    cloudOnly: true,
    features: [
      {
        title: "Espaço",
        description: "Armazenamento total permitido por workspace",
        cloud: {
          free: "5GB",
          one: false,
          pro: "1 TB",
          business: "5 TB",
          enterprise: "Personalizado",
        },
      },
      {
        title: "Tamanho máximo de arquivo",
        description: "Limite para uploads no seu workspace",
        cloud: {
          free: "5 MB",
          one: false,
          pro: "100 MB",
          business: "200 MB",
          enterprise: "Personalizado",
        },
      },
    ],
  },
  {
    id: "security",
    title: "Segurança",
    features: [
      {
        title: "SAML",
        description: "Use a implementação oficial de SAML\ne proteja o Tasks com qualquer IdP.",
        cloud: {
          free: false,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "OIDC",
        description: "Use a implementação oficial de OIDC\ne proteja o Tasks com qualquer IdP.",
        selfHostedOnly: true,
        cloud: {
          free: false,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Segurança de domínio",
        description:
          "Escolha outros domínios que podem se autenticar no\nseu workspace do Tasks ou restrinja a um único domínio.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Autenticação de dois fatores e passkeys",
        description:
          "Proteja seu workspace do Tasks com autenticação de dois fatores\nvinculada ao dispositivo e passkeys. ",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Política de senhas",
        description: "Defina políticas de senha personalizadas de acordo com seus\nrequisitos de compliance.",
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "LDAP",
        description: "Use a implementação oficial de LDAP e proteja\nseu workspace do Tasks com seu servidor LDAP.",
        comingSoon: true,
        cloud: {
          free: false,
          one: false,
          pro: false,
          business: false,
          enterprise: true,
        },
      },
    ],
  },
  {
    id: "self-hosted",
    title: "Auto-hospedado",
    selfHostedOnly: true,
    features: [
      {
        title: "Modo administrador",
        description:
          "Gerencie melhor sua instância auto-hospedada do Tasks com\numa interface de administração da instância.",
        cloud: {
          free: true,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Implantação com um clique",
        description: "Instale e implante seu Tasks auto-hospedado em qualquer\nnuvem privada com um único comando.",
        cloud: {
          free: false,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "App no Marketplace da Digital Ocean",
        description: "Obtenha nosso app compatível com a Digital Ocean no\nmarketplace deles.",
        cloud: {
          free: false,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "App para a plataforma Heroku",
        description: "Obtenha nosso app compatível com a plataforma Heroku e implante\nno Heroku com facilidade.",
        cloud: {
          free: false,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "AWS AMI",
        description: "Obtenha nosso app compatível com AMI no marketplace\nda AWS.",
        cloud: {
          free: false,
          one: true,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
      {
        title: "Implantações privadas",
        description: "Tenha nosso app em nuvem hospedado em uma nuvem privada\ngerenciada por nós.",
        comingSoon: true,
        cloud: {
          free: false,
          one: false,
          pro: false,
          business: false,
          enterprise: true,
        },
      },
    ],
  },
  {
    id: "support",
    title: "Suporte",
    features: [
      {
        title: "Canais",
        description: "Tenha acesso a um ou mais canais de suporte\nconforme o seu plano.",
        cloud: {
          free: (
            <>
              <ForumIcon className="size-4" />
            </>
          ),
          one: (
            <div className="flex items-center gap-1">
              <Mail className="size-4 flex-shrink-0" />
              <ForumIcon className="size-4 flex-shrink-0" />
            </div>
          ),
          pro: (
            <div className="flex items-center gap-1">
              <Mail className="size-4 flex-shrink-0" />
              <ForumIcon className="size-4 flex-shrink-0" />
              <MessageCircle className="size-4 flex-shrink-0" />
            </div>
          ),
          business: "Serviços profissionais\ncompletos",
          enterprise: "Serviços profissionais\ncompletos",
        },
      },
      {
        title: "SLA",
        description: (
          <>
            Tenha SLAs adequados ao seu negócio nos planos superiores. Os SLAs são por prioridade da tarefa, e níveis{" "}
            <a href="https://conjosa.com.br" target="_blank" rel="noopener noreferrer" className="underline">
              podem ser solicitados
            </a>
            .
          </>
        ),
        cloud: {
          free: false,
          one: false,
          pro: true,
          business: true,
          enterprise: true,
        },
      },
    ],
  },
];

export const PLANE_PLANS: PlanePlans = {
  planDetails: {
    free: {
      id: EProductSubscriptionEnum.FREE,
      name: "Gratuito",
      monthlyPrice: 0,
      yearlyPrice: 0,
      isActive: true,
    },
    one: {
      id: EProductSubscriptionEnum.ONE,
      name: "One",
      monthlyPrice: 799,
      yearlyPrice: 799,
      monthlyPriceSecondaryDescription: "por workspace",
      yearlyPriceSecondaryDescription: "por workspace",
      buttonCTA: "Fazer upgrade",
      isActive: false,
    },
    pro: {
      id: EProductSubscriptionEnum.PRO,
      name: "Pro",
      monthlyPrice: 8,
      yearlyPrice: 6,
      monthlyPriceSecondaryDescription: "cobrado mensalmente",
      yearlyPriceSecondaryDescription: "cobrado anualmente",
      buttonCTA: "Fazer upgrade",
      isActive: true,
    },
    business: {
      id: EProductSubscriptionEnum.BUSINESS,
      name: "Business",
      monthlyPriceSecondaryDescription: "cobrado mensalmente",
      yearlyPriceSecondaryDescription: "cobrado anualmente",
      buttonCTA: "Falar com vendas",
      isActive: false,
    },
    enterprise: {
      id: EProductSubscriptionEnum.ENTERPRISE,
      name: "Enterprise",
      monthlyPriceSecondaryDescription: "cobrado mensalmente",
      yearlyPriceSecondaryDescription: "cobrado anualmente",
      buttonCTA: "Falar com vendas",
      isActive: false,
    },
  },
  planHighlights: {
    free: ["Até 12 usuários", "Páginas", "Projetos ilimitados", "Ciclos e módulos ilimitados"],
    one: ["Até 50 usuários", "OIDC e SAML", "Ciclos ativos", "Controle de tempo limitado"],
    pro: [
      "Usuários ilimitados",
      "Tarefas + propriedades personalizadas",
      "Modelos de tarefa",
      "Controle de tempo completo",
    ],
    business: ["RBAC", "Modelos de projeto", "Linhas de base e desvios", "Relatórios personalizados"],
    enterprise: ["Implantações privadas + gerenciadas", "GAC", "Suporte a LDAP", "Bancos de dados + fórmulas"],
  },
  planComparison: PLANS_COMPARISON_LIST,
};
