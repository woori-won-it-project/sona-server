// 이슈에 담당자가 지정되면 dev 기준 브랜치를 만들고 이슈에 연결한다.
// 제목 형식: 이슈 템플릿의 "[Feat] 요약" (대소문자 무관) 또는 커밋 형식 "FEAT: 요약" → 브랜치 feat/<이슈번호>
const BASE_BRANCH = 'dev'; // 브랜치를 딸 기준 브랜치
const TYPES = 'feature|feat|fix|refactor|docs|test|chore|ci|build|style|perf';
const ALIAS = { feature: 'feat' }; // 템플릿 이름 [Feature] 도 feat 로
const BRACKET = new RegExp(`^\\[(${TYPES})\\]\\s*\\S`, 'i');      // [Feat] 요약
const COLON = new RegExp(`^(${TYPES.toUpperCase()}):\\s+\\S`);       // FEAT: 요약

function branchName(title, number) {
  const t = (title || '').trim();
  const m = BRACKET.exec(t) || COLON.exec(t);
  if (!m) return null;
  const type = m[1].toLowerCase();
  return `${ALIAS[type] || type}/${number}`;
}

async function run({ github, context, core }) {
  const issue = context.payload.issue;
  const { owner, repo } = context.repo;
  const comment = (body) =>
    github.rest.issues.createComment({ owner, repo, issue_number: issue.number, body });

  const name = branchName(issue.title, issue.number);
  if (!name) {
    await comment('브랜치를 만들지 않았어요. 제목을 `[Feat] 요약` 형식으로 고친 뒤 담당자를 다시 지정해 주세요.\n' +
      '(사용 가능: Feat, Fix, Refactor, Docs, Test, Chore, Ci, Build, Style, Perf)');
    core.info(`skip: title prefix missing (#${issue.number})`);
    return { status: 'skipped' };
  }

  try {
    await github.rest.git.getRef({ owner, repo, ref: `heads/${name}` });
    await comment(`브랜치 \`${name}\` 이 이미 있어요. 새로 만들지 않았어요.\n\n` +
      '```bash\ngit fetch origin && git checkout ' + name + '\n```');
    return { status: 'exists', name };
  } catch (e) {
    if (e.status !== 404) throw e;
  }

  const { data: base } = await github.rest.git.getRef({ owner, repo, ref: `heads/${BASE_BRANCH}` });
  const ids = await github.graphql(
    `query($owner:String!,$repo:String!,$number:Int!){
       repository(owner:$owner,name:$repo){ id issue(number:$number){ id } } }`,
    { owner, repo, number: issue.number });
  await github.graphql(
    `mutation($repositoryId:ID!,$issueId:ID!,$oid:GitObjectID!,$name:String!){
       createLinkedBranch(input:{repositoryId:$repositoryId,issueId:$issueId,oid:$oid,name:$name}){
         linkedBranch{ ref{ name } } } }`,
    { repositoryId: ids.repository.id, issueId: ids.repository.issue.id, oid: base.object.sha, name });

  await comment(`브랜치 \`${name}\` 을 \`${BASE_BRANCH}\` 기준으로 만들었어요.\n\n` +
    '```bash\ngit fetch origin && git checkout ' + name + '\n```\n\n' +
    `PR 본문 '관련 이슈'에 \`Closes #${issue.number}\` 를 넣어 주세요.`);
  return { status: 'created', name };
}

module.exports = run;
module.exports.branchName = branchName;
